#!/usr/bin/env python3
"""apsystems_daemon.py — polls the APsystems OpenAPI (EMA cloud) every 5 minutes
and streams real solar production into HA via the shared JSON state file.

Why this exists: the old fetch_solar.py hourly cron only read the system-level
hourly endpoint, so "current power" was derived from the in-progress hour bucket
(always 0 -> the power sensor read 0 W all day), and any API hiccup (notably
code 1001 "No data" at night/day-rollover) zeroed EVERY sensor including
lifetime totals. The ECU-level endpoints give real 5-minute telemetry:

  /user/api/v2/systems/{sid}/devices/ecu/energy/{eid}?energy_level=minutely
      -> {time[], power[] (W), energy[] (kWh/slot), today (kWh)}
  /user/api/v2/systems/{sid}/devices/inverter/batch/energy/{eid}?energy_level=power
      -> {time[], power: {<inverter>-<channel>: [W, ...]}}   (per-panel)
  /user/api/v2/systems/summary/{sid}
      -> {today, month, year, lifetime} kWh

Auth: per-request HmacSHA256 headers (X-CA-*), signed string
"{ts_ms}/{nonce}/{app_id}/{last_path_segment}/GET/HmacSHA256".
Credentials come from the environment (EnvironmentFile in the systemd unit) —
never hardcode them here. Required vars: APS_APP_ID, APS_APP_SECRET,
APS_SYSTEM_ID, APS_ECU_ID.

Error policy: values are STICKY — a failed cycle never zeroes the state file.
1001 ("no data": pre-dawn / day rollover) is a normal night condition, not an
error. 7002/7003 (server busy) back off one extra cycle. Auth problems set
status="auth_error" so HA sensors flip unavailable via the stale_min field.

Outputs (atomic write, both files, identical content):
  STATE  (default /opt/homeassistant/apsystems.json)  — HA command_line sensors
  HERMES (argv[2], optional legacy consumer)          — keeps fetch_solar keys

Usage: apsystems_daemon.py [state_file] [hermes_file]
Docs: reference/apsystems-openapi.md
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

STATE = sys.argv[1] if len(sys.argv) > 1 else "/opt/homeassistant/apsystems.json"
HERMES = sys.argv[2] if len(sys.argv) > 2 else ""

BASE_URL = "https://api.apsystemsema.com:9282"
SITE_TZ = "Canada/Eastern"  # confirmed by /systems/inverters/{sid}
CAPACITY_KW = 11.44

POLL_SEC = 300          # matches the ECU's ~5 min cloud upload cadence
SUMMARY_EVERY = 3       # fetch month/year/lifetime every 3rd cycle (~15 min)
STALE_UNAVAILABLE_MIN = 360  # HA availability template cuts off past this

# Response codes (manual annex 4.1). 1001=no data (night); 7002/7003=busy.
CODE_OK = 0
CODE_NO_DATA = 1001
CODE_BUSY = (7002, 7003)


def _env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"apsystems_daemon: missing required env var {name} "
                 f"(set via EnvironmentFile, see pi-config/apsystems-solar.service)")
    return v


APP_ID = _env("APS_APP_ID")
APP_SECRET = _env("APS_APP_SECRET")
SYSTEM_ID = _env("APS_SYSTEM_ID")
ECU_ID = _env("APS_ECU_ID")


def api_get(path):
    """Signed GET. Returns parsed JSON dict. Raises on transport/HTTP errors."""
    rp = path.split("/")[-1].split("?")[0]  # sign with the last path segment only
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sig_str = f"{ts}/{nonce}/{APP_ID}/{rp}/GET/HmacSHA256"
    sig = base64.b64encode(
        hmac.new(APP_SECRET.encode(), sig_str.encode(), hashlib.sha256).digest()
    ).decode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={
            "X-CA-AppId": APP_ID,
            "X-CA-Timestamp": ts,
            "X-CA-Nonce": nonce,
            "X-CA-Signature-Method": "HmacSHA256",
            "X-CA-Signature": sig,
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def local_now():
    if ZoneInfo:
        return datetime.now(ZoneInfo(SITE_TZ))
    return datetime.now()  # Pi runs in America/Toronto anyway


def slot_minutes(hhmm):
    h, m = hhmm.split(":")[:2]
    return int(h) * 60 + int(m)


def fetch_minutely(day_str):
    """Returns (power_w, today_kwh, current_hour_kwh, last_slot, data_age_min)."""
    d = api_get(
        f"/user/api/v2/systems/{SYSTEM_ID}/devices/ecu/energy/{ECU_ID}"
        f"?energy_level=minutely&date_range={day_str}"
    )
    code = d.get("code")
    if code == CODE_NO_DATA:
        return 0, 0.0, 0.0, None, None  # pre-dawn / day rollover: legitimately zero
    if code != CODE_OK:
        raise RuntimeError(f"minutely code={code}")
    data = d.get("data") or {}
    times = data.get("time") or []
    powers = data.get("power") or []
    energies = data.get("energy") or []
    if not times:
        return 0, 0.0, 0.0, None, None

    last_w = int(float(powers[-1])) if powers else 0
    now = local_now()
    now_min = now.hour * 60 + now.minute
    try:
        age = max(0, (now_min - slot_minutes(times[-1])))
    except ValueError:
        age = None
    # Legacy compat: energy generated within the current local hour
    cur_hour = sum(
        float(e) for t, e in zip(times, energies) if t.startswith(f"{now.hour:02d}:")
    ) or 0.0
    return (
        last_w,
        float(data.get("today") or 0.0),
        round(cur_hour, 4),
        times[-1],
        age,
    )


def fetch_inverter_power(day_str):
    """Returns {inverter-channel: current_w} or {} when unavailable."""
    d = api_get(
        f"/user/api/v2/systems/{SYSTEM_ID}/devices/inverter/batch/energy/{ECU_ID}"
        f"?energy_level=power&date_range={day_str}"
    )
    if d.get("code") != CODE_OK:
        return {}
    power = (d.get("data") or {}).get("power") or {}
    out = {}
    for chan, series in power.items():
        try:
            out[chan] = int(float(series[-1])) if series else 0
        except (TypeError, ValueError, IndexError):
            out[chan] = 0
    return out


def fetch_summary():
    """Returns (month, year, lifetime) kWh or None on failure."""
    d = api_get(f"/user/api/v2/systems/summary/{SYSTEM_ID}")
    if d.get("code") != CODE_OK:
        return None
    sd = d.get("data") or {}
    return (
        float(sd.get("month") or 0),
        float(sd.get("year") or 0),
        float(sd.get("lifetime") or 0),
    )


def fetch_daily(ym):
    """Daily kWh list for month 'YYYY-MM' (index 0 = day 1), or None if no data."""
    d = api_get(
        f"/user/api/v2/systems/energy/{SYSTEM_ID}?energy_level=daily&date_range={ym}"
    )
    if d.get("code") != CODE_OK:
        return None
    return [float(v or 0) for v in (d.get("data") or [])]


def refresh_yesterday():
    """Final kWh for yesterday, from the daily endpoint (2 calls/day).

    Retries every cycle until yesterday's date is resolved; a legitimate
    zero-production day still resolves (code 0 with a 0.0 entry).
    """
    y = local_now() - timedelta(days=1)
    y_str = y.strftime("%Y-%m-%d")
    for ym in (y.strftime("%Y-%m"), (y - timedelta(days=1)).strftime("%Y-%m")):
        days = fetch_daily(ym)
        if days is None:
            continue
        idx = y.day - 1
        if idx < len(days):
            return y_str, days[idx]
    return None  # no data yet — retry next cycle


def atomic_write(path, payload):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def main():
    sticky = {}  # last good values — never regress to zeros on transient errors
    cycle = 0
    last_ok = None  # epoch of last fully successful cycle
    print(f"apsystems_daemon: polling every {POLL_SEC}s -> {STATE}", flush=True)

    while True:
        day_str = local_now().strftime("%Y-%m-%d")
        cycle += 1
        status = "ok"
        error = ""
        try:
            power_w, today_kwh, cur_hour, last_slot, age = fetch_minutely(day_str)
            inverters = fetch_inverter_power(day_str)
            if cycle % SUMMARY_EVERY == 1 or "month_kwh" not in sticky:
                s = fetch_summary()
                if s:
                    sticky["month_kwh"], sticky["year_kwh"], sticky["lifetime_kwh"] = s
            y_str = (local_now() - timedelta(days=1)).strftime("%Y-%m-%d")
            if sticky.get("yesterday_date") != y_str:
                yd = refresh_yesterday()
                if yd:
                    sticky["yesterday_date"], sticky["yesterday_kwh"] = yd
            sticky.update(
                power_w=power_w, today_kwh=today_kwh, current_hour_kwh=cur_hour,
                last_slot_time=last_slot or "", data_age_min=age if age is not None else -1,
                inverters=inverters,
            )
            last_ok = time.time()
        except urllib.error.HTTPError as e:
            error = f"http {e.code}"
            status = "auth_error" if e.code in (401, 403) else "error"
        except Exception as e:  # noqa: BLE001 — daemon must never die on API state
            error = str(e)[:200]
            status = "error"

        stale_min = int((time.time() - last_ok) / 60) if last_ok else 9999
        if status != "ok":
            print(f"cycle {cycle} failed ({error}); serving sticky data "
                  f"(stale {stale_min} min)", flush=True)

        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        payload = {
            # keys the HA command_line sensors read
            "power_w": sticky.get("power_w", 0),
            "today_kwh": sticky.get("today_kwh", 0.0),
            "month_kwh": sticky.get("month_kwh", 0.0),
            "year_kwh": sticky.get("year_kwh", 0.0),
            "lifetime_kwh": sticky.get("lifetime_kwh", 0.0),
            "inverters": sticky.get("inverters", {}),
            "last_slot_time": sticky.get("last_slot_time", ""),
            "data_age_min": sticky.get("data_age_min", -1),
            "capacity_kw": CAPACITY_KW,
            "yesterday_date": sticky.get("yesterday_date", ""),
            "yesterday_kwh": sticky.get("yesterday_kwh", 0.0),
            "updated": now_iso,
            "status": status,
            "stale_min": stale_min,
            # legacy keys kept for ~/.hermes consumers (old fetch_solar.py schema)
            "power_approx_w": sticky.get("power_w", 0),
            "current_hour_kwh": sticky.get("current_hour_kwh", 0.0),
            "last_updated": now_iso,
        }
        try:
            atomic_write(STATE, payload)
            if HERMES:
                atomic_write(HERMES, payload)
        except Exception as e:  # noqa: BLE001
            print(f"state write failed: {e}", flush=True)

        # 7002/7003 backoff: double the sleep for one cycle to be polite
        sleep = POLL_SEC * 2 if "7002" in error or "7003" in error else POLL_SEC
        time.sleep(sleep)


if __name__ == "__main__":
    main()
