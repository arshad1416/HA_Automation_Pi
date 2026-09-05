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
| 2005 | app account access limit exceeded | regenerate keys at developer portal |
| 4000/4001 | bad parameter (e.g. invalid `energy_level`) | fix the call |
| 7002/7003 | too many requests / busy | daemon doubles its sleep one cycle |
| No documented per-day call quota; a 5-min poll of 2–3 endpoints has run fine. |

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
