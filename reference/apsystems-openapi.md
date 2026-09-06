# APsystems OpenAPI + local ECU SunSpec Modbus — reference & HA integration

System: 11.44 kW, 13× APsystems **DS3-L** dual-channel microinverters behind an
**ECU-R** (ID 216000181195, MAC 80:97:1b:07:25:c3, at **192.168.0.134 on the
Eero WiFi LAN**). Cloud account: APsystems EMA. Reverse-engineered 2026-09-05.

## Primary source: local ECU SunSpec Modbus TCP (daemon v1.3+)

Official doc: APsystems "SunSpec Modbus" Rev 3.2 (global.apsystems.com, 2024/03
`SunSpec-Modbus.pdf`); supported on ECU-R 2160 firmware ≥ 1.3.7. Already
enabled on our unit — no EMA toggle was needed. Port 8899 (old local protocol)
is closed by firmware; Modbus is the sanctioned local surface.

- `192.168.0.134:502`, **Modbus unit ID 0** (ECU aggregate; units 1..N per
  inverter time out — not enabled). FC3 holding registers, base 40000.
- ⚠️ **Network gotcha**: the house has TWO parallel 192.168.0.0/24 LANs. The
  ECU is on the Eero (WiFi) one; the Pi's wired eth2 is on the other, and its
  default 192.168.0.x route goes out the wrong interface. The systemd unit
  pins `192.168.0.134/32 dev wlan0` via ExecStartPre before the daemon starts.

Register map (verified live + cross-checked against the PDF):

| Register | Type | Meaning |
|---|---|---|
| 40000 | 2×char | "SunS" signature |
| 40002/40003 | u16 | DID=1 / LEN=66 (common: APsystems / DS3 / serial) |
| 40072, 40073 | u16 | split-phase leg currents (×0.1 A) |
| **40084** | u16 | **total power W (live; tracks clouds within ~150 s)** |
| 40086 | u16 | grid voltage (×0.04 V) |
| 40088 / 40090 | u16 | VA / VAR |
| 40092 | u16 | ~Hz (scale unverified) |
| 40124, 40126 | float32 | PDF-documented float-current variants |
| 40214, 40216 | float32 | inverter temperatures °C |
| **40230** (40232 dup) | float32 | **today's energy kWh** (~5 min refresh; ⚠️ the register resets itself after sunset — read 0.0 at 22:14 after a ~33 kWh day — so the daemon tracks the day's peak and displays it until local midnight) |
| 40188 | — | write: inverter on/off (0x9CFC) — DO NOT WRITE |

Aggregate only — no per-panel registers (community-confirmed); per-inverter
detail still comes from the cloud batch endpoint. Lifetime/month/year also
cloud-only. Cloud call budget with local primary: ~75/day, far under quota.

## Transport & auth (cloud OpenAPI)

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
| **2005** | **Access limit exceeded** — observed 2026-09-05: ~720 calls then lockout. **Reset is NOT at a fixed hour** (12:00 EDT / CST midnight theory falsified — still locked at 22:14 EDT, >21 h after exhaustion). Best remaining fit: **rolling ~24 h window** (~720 calls) — would free ~01:00 EDT when the burst ages out; verify then. | daemon is local-first so live data ignores the quota entirely; cloud extras soft-fail (logged `cloud … code=2005`) and retry; backfill checkpoints and exits, resuming on later days |
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
ECU (local SunSpec Modbus, 192.168.0.134:502 unit 0, via wlan0 route)  ── PRIMARY ──┐
APsystems cloud ──(summary/batch/yesterday, ~75 calls/day) ── totals & per-panel ──┤
                                                                                    ▼
                                     apsystems_daemon.py [systemd: apsystems-solar.service]
                                                   │ atomic write
                                                   ├─ /opt/homeassistant/apsystems.json  (→ /config/ in container)
                                                   └─ ~/.hermes/market-intel/solar_data.json (legacy schema kept)
HA command_line sensors (configuration.yaml): Solar Power Now (60 s), Energy Today (2 min),
  Month/Year/Lifetime (15/30/60 min), Yesterday — all availability-gated on stale_min < 360.
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
