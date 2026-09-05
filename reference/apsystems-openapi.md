# APsystems OpenAPI — reverse-engineered reference & HA integration

System: 11.44 kW, 13× APsystems **DS3-L** dual-channel microinverters behind an
**ECU-R** (cloud-connected — the ECU is **not** reachable on the LAN; the old
`ecu_discover.py` */15 cron never found port 8899 and can be retired).
Cloud account: APsystems EMA. Reverse-engineered 2026-09-05.

## Transport & auth

- Base URL: `https://api.apsystemsema.com:9282`
- Official manual: search "APsystems OpenAPI User Manual End User EN" — this
  file distills what we verified live.
- Every request is a GET signed with HmacSHA256 headers (no session token):

```
ts    = epoch milliseconds
nonce = uuid4().hex
rp    = LAST PATH SEGMENT of the URL (before any query string)   # verified live
sig   = base64( HMAC_SHA256( app_secret, f"{ts}/{nonce}/{app_id}/{rp}/GET/HmacSHA256" ) )
headers: X-CA-AppId, X-CA-Timestamp, X-CA-Nonce,
         X-CA-Signature-Method: HmacSHA256, X-CA-Signature
```

- Credentials live in `/home/arshad14/.apsystems.env` on the Pi (600,
  arshad14) — `APS_APP_ID`, `APS_APP_SECRET`, `APS_SYSTEM_ID`,
  `APS_ECU_ID`. Never commit them. Keys come from the APsystems developer
  registration tied to the EMA account (error 2005 = regenerate keys).

## Verified endpoints (16 documented; the ones we use marked ★)

| Endpoint | What it gives |
|---|---|
| ★ `/user/api/v2/systems/summary/{sid}` | today/month/year/lifetime kWh (`today` is **null** pre-dawn) |
| `/user/api/v2/systems/energy/{sid}?energy_level=hourly&date_range=YYYY-MM-DD` | 24 hourly kWh buckets; current hour stays 0 until the hour closes |
| ★ `/user/api/v2/systems/{sid}/devices/ecu/energy/{eid}?energy_level=minutely&date_range=YYYY-MM-DD` | **5-min telemetry**: `time[]` (HH:mm), `power[]` (W), `energy[]` (kWh/slot), `today` running total. Slots have gaps when the ECU is offline. |
| ★ `/user/api/v2/systems/{sid}/devices/inverter/batch/energy/{eid}?energy_level=power&date_range=YYYY-MM-DD` | **Per-panel power**: `power: {"<inverter_uid>-<channel>": [W,...]}` aligned to `time[]` |
| `/user/api/v2/systems/inverters/{sid}` | inverter inventory (uid, model/subType, site timezone) |
| `/user/api/v2/systems/{sid}/devices/ecu/summary/{eid}` | ECU-level today/month/year/lifetime |
| others (system details, meters, per-inverter summary/energy, storage) | unused; see manual |

`energy_level` accepted values: `minutely, hourly, daily, monthly, yearly`.
`date_range` format: `yyyy-MM-dd` (minutely/hourly), `yyyy-MM` (daily),
`yyyy` (monthly). Future dates are rejected.

## Response codes (annex 4.1) — the ones that matter

| Code | Meaning | How we handle it |
|---|---|---|
| 0 | OK | — |
| **1001** | **No data** (pre-dawn, day rollover, future date) | normal night condition: power 0, totals sticky — NOT an error (the old cron treated it as fatal and zeroed every sensor) |
| **2005** | **Daily access limit exceeded** — observed 2026-09-05: quota ≈ 340 calls per endpoint / ~720 account-wide per day. Reset is at **12:00 EDT (China Standard Time midnight)** — verified 2026-09-06 by elimination: it did not reset at UTC midnight, at 24 h rolling, or overnight EDT. A naive poll-everything-every-5-min design (864 calls/day) blows it by afternoon. | daemon budgets ~293 calls/day and backs off 30 min on 2005; backfill caps itself at 380 calls/day (`--max-calls=380` in the daily cron) so archive completion never starves the live daemon |
| 7002/7003 | too many requests / busy | daemon doubles its sleep one cycle |
| No documented quota in the manual — the annex only says "access limit exceeded". |

## Daemon call budget (v1.2, 2026-09-05)

Telemetry is fetched only during **06:00–21:00 local** (~293 calls/day):
minutely every 5 min (174) + inverter batch & summary every 3rd day-cycle
(58 + 59) + yesterday/month-rollover daily calls (2). Night cycles make no
telemetry calls and still count as healthy (`stale_min` stays 0 — the
availability gate must not flap overnight). On boot the daemon **hydrates its
sticky state from the state file**, so restarts don't re-fetch (or hit quota)
for values it already holds. Values are sticky — quota outages degrade to
"stale" (sensors unavailable after 6 h), never to zeros.

## Pipeline into HA

```
APsystems cloud ──(5 min poll, signed GETs)── apsystems_daemon.py [systemd: apsystems-solar.service]
                                                   │ atomic write
                                                   ├─ /opt/homeassistant/apsystems.json  (→ /config/ in container)
                                                   └─ ~/.hermes/market-intel/solar_data.json (legacy schema kept)
HA command_line sensors (configuration.yaml): Solar Power Now (60 s), Energy Today (2 min),
  Month/Year/Lifetime (15/30/60 min) — all availability-gated on stale_min < 360.
```

Daemon invariants (learned from the old cron's failures):

- values are **sticky** — a failed cycle never zeroes the state file;
- current power = last 5-min slot of the **minutely** endpoint (real W), never
  the in-progress hourly bucket;
- per-inverter power lands in the `inverters` attribute of Solar Power Now;
- `stale_min` = minutes since last good cycle; HA flips sensors unavailable
  after 6 h of failure.

## Local history archive (`apsystems_history.json`)

`apsystems_backfill.py` (run manually, resumable with `--resume`) downloads
everything the cloud still holds into `/opt/homeassistant/apsystems_history.json`:

- `yearly[]` — lifetime (system commissioned **October 2024**, partial first year)
- `monthly{year: [12 kWh]}` — full lifetime
- `daily{date: kWh}` — **complete: 705 days, sums to 23,535.73 kWh vs API lifetime 23,535.85**
- `hourly{date: [24 kWh]}` + `minutely{date: …}` — 340 days (2024-10-12 → 2025-09-18) fetched so far; the 2025-09-19 → present tail exists server-side but hit the **daily quota** mid-run
- `--resume` skips already-archived days; `--only=hourly|minutely` splits quota across days; on quota exhaustion it checkpoints (`~/.apsystems_backfill_checkpoint.json`) and exits 2.

A self-removing Pi cron (`~/apsystems_backfill_daily.sh`, 13:30 daily)
continues the backfill until `minutely_days ≥ 690`, then deletes its own
crontab entry. Manual rerun: `ssh pi-lan 'set -a; . ~/.apsystems.env; set +a; python3 /opt/homeassistant/apsystems_backfill.py --resume'`.
Ideas for using it: join `hourly` with the Alectra UsageAPI hourly consumption
(see memory/alectra notes) to quantify solar self-consumption and TOU-shift
value; `daily` feeds year-over-year monthly comparisons.

## Deployment record (2026-09-05)

- `apsystems-solar.service` active on the Pi (systemd, user arshad14,
  `Restart=always`); creds in `/home/arshad14/.apsystems.env` (600).
- Old `fetch_solar.py` hourly cron and `ecu_discover.py` */15 cron REMOVED.
  ⚠️ `ecu_discover.py` still embeds an HA long-lived token — delete the file
  and revoke the token in HA UI (Profile → Security → Long-lived tokens).
- HA restarted; sensors verified: power/today/month/year/lifetime/yesterday.

## Old pipeline (retired)

`fetch_solar.py` hourly cron: hourly endpoint only, `power_approx_w` =
in-progress-hour bucket (always 0 W — sensor was dead), error 1001 at midnight
zeroed all totals for hours. `ecu_discover.py` */15 cron: LAN scan that never
succeeded (ECU is cloud-only) and embeds an HA long-lived token — remove both
crontab lines when the daemon is deployed.

The unused `custom_components/aps_api_client` (EMA app-API v1 client,
username/password + "aps2020" checkcode HMAC, port 9223) and HACS
`custom_components/apsystems_ecu_reader` (needs ECU on LAN — not our case)
remain in the tree but are not configured.
