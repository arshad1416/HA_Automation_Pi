#!/usr/bin/env python3
"""apsystems_daemon.py — streams real solar production into HA.

PRIMARY source (v1.3): the ECU's local **SunSpec Modbus TCP** interface
(APsystems doc "SunSpec Modbus" Rev 3.2; unit ID 0, port 502). No quota, no
cloud, works at night. Falls back to the APsystems OpenAPI cloud when the ECU
is unreachable.

Local register map (verified live 2026-09-05, cross-referenced with the PDF):
  model 101 int block @40070 (LEN 50):
    40072/40073 currents (split-phase legs, ~0.1 A lsb)
    40084 total power W  (live — observed tracking clouds within 150 s)
    40086 grid voltage (×0.04 V)   40088 VA   40090 VAR   40092 ~Hz
  model 114 float32 block @40184 (LEN 48):
    40214/40216 inverter temps °C
    40230 today's energy kWh (40232 near-duplicate) — ~5 min refresh

Cloud OpenAPI supplies what Modbus doesn't: month/year/lifetime totals,
yesterday (daily endpoint), per-inverter panel map — ~75 calls/day, far under
the ~720/day quota (code 2005, resets 12:00 EDT).

Auth (cloud): HmacSHA256 X-CA-* headers, creds from the environment
(EnvironmentFile in the systemd unit) — APS_APP_ID, APS_APP_SECRET,
APS_SYSTEM_ID, APS_ECU_ID. The ECU's LAN address is APS_ECU_IP (the unit file
adds a /32 route via wlan0 — the ECU lives on the Eero WiFi network, which is
a parallel 192.168.0.0/24 to the Pi's wired one).

Error policy: values are STICKY — a failed cycle never zeroes the state file.
1001 (night/day rollover) and local power=0 are normal conditions, not errors.
2005 (quota) backs off 30 min. Local and cloud failures degrade to "stale".

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
import socket
import struct
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
SUMMARY_EVERY = 3       # fetch inverter/summary data every 3rd DAY cycle (~15 min)
STALE_UNAVAILABLE_MIN = 360  # HA availability template cuts off past this
DAY_START_H, DAY_END_H = 6, 21   # local hours in which telemetry is fetched
QUOTA_BACKOFF_SEC = 1800  # code 2005 (daily access limit) — retry in 30 min

# Observed 2026-09-05: the app account has a DAILY call quota (~340 per
# endpoint / ~720 account-wide; code 2005 when exhausted). The old "poll every
# endpoint every 5 min around the clock" design (864 calls/day) would blow it
# by mid-afternoon. Budget below stays under ~300/day:
#   minutely 174 (every 5 min, 06:00-21:00) + batch 58 + summary 59 + daily 2.

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

# ECU local SunSpec Modbus (primary source). The unit file installs a /32
# route via wlan0 — the ECU is on the Eero WiFi LAN, a parallel 192.168.0.0/24
# to the Pi's wired one, so plain routing picks the wrong interface.
ECU_IP = os.environ.get("APS_ECU_IP", "192.168.0.134").strip()
ECU_MODBUS_PORT = 502
MODBUS_UNIT = 0  # only unit 0 (ECU aggregate) responds; inverters not exposed


def modbus_read3(start, qty):
    """FC3 read holding registers from the ECU. Returns tuple of uint16."""
    pdu = struct.pack(">BHH", 3, start, qty)
    frame = struct.pack(">HHHB", 0x4242, 0, len(pdu) + 1, MODBUS_UNIT) + pdu
    s = socket.create_connection((ECU_IP, ECU_MODBUS_PORT), timeout=5)
    try:
        s.sendall(frame)
        r = s.recv(2048)
    finally:
        s.close()
    if len(r) < 9 or r[7] != 3:
        raise RuntimeError("bad modbus response")
    bc = r[8]
    return struct.unpack(">%dH" % (bc // 2), r[9:9 + bc])


def _f32(regs, i):
    return struct.unpack(">f", struct.pack(">HH", regs[i], regs[i + 1]))[0]


def _sane(v, lo, hi):
    return v is not None and v == v and lo <= v <= hi


def fetch_local():
    """Read the ECU's SunSpec aggregate (unit 0). Raises on any failure.

    Model 101 int block data @40072 (reg 40084 = total W, live);
    model 114 float32 tail (40214/40216 temps, 40230 today kWh).
    N/A markers (0xFFFF/0xFFFE) become None rather than garbage numbers.
    """
    r101 = modbus_read3(40070, 30)
    r114 = modbus_read3(40210, 24)

    def i101(addr):
        v = r101[addr - 40070]
        return None if v in (65535, 65534) else v

    power_w = i101(40084)
    voltage = i101(40086)
    today_kwh = None
    for idx in (20, 22):  # 40230 then 40232 (near-duplicate accumulator)
        try:
            v = _f32(r114, idx)
        except (IndexError, struct.error):
            continue
        if _sane(v, 0, 500):
            today_kwh = round(v, 3)
            break
    return {
        "power_w": int(power_w) if power_w is not None else 0,
        "today_kwh": today_kwh,
        "voltage_v": round(voltage * 0.04, 1) if voltage is not None else None,
        "va": i101(40088),
        "temp_c1": round(_f32(r114, 4), 1) if _sane(_f32(r114, 4), -40, 120) else None,
        "temp_c2": round(_f32(r114, 6), 1) if _sane(_f32(r114, 6), -40, 120) else None,
    }


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
        if d.get("code") != CODE_NO_DATA:
            print(f"cloud inverter-batch code={d.get('code')}", flush=True)
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
        if d.get("code") != CODE_NO_DATA:
            print(f"cloud summary code={d.get('code')}", flush=True)
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


def record_today(sticky, val, day_str):
    """The ECU's local today-accumulator resets itself after sunset (observed
    2026-09-05: read 0.0 kWh at 22:14 after a ~33 kWh day). Track the day's
    peak so 'Energy Today' holds the final daily total until local midnight."""
    if sticky.get("today_peak_date") != day_str:
        sticky["today_peak_date"] = day_str
        sticky["today_peak_kwh"] = 0.0
    if val is not None:
        sticky["today_date"] = day_str
        if val > sticky.get("today_peak_kwh", 0.0):
            sticky["today_peak_kwh"] = val
    sticky["today_kwh"] = (
        sticky.get("today_peak_kwh", 0.0) if sticky.get("today_date") == day_str else 0.0
    )


def load_existing(path):
    """Hydrate sticky values from a previous state file so a daemon restart
    doesn't re-fetch (or fail on quota) for things it already knows."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    prev = load_existing(STATE)
    sticky = {
        k: v for k, v in prev.items()
        if k in ("power_w", "today_kwh", "month_kwh", "year_kwh", "lifetime_kwh",
                 "current_hour_kwh", "last_slot_time", "data_age_min", "inverters",
                 "yesterday_date", "yesterday_kwh", "month_date", "today_date",
                 "today_peak_kwh", "today_peak_date")
    }
    if "month_date" not in sticky and "updated" in prev:
        # month/year/lifetime totals were last fetched within this month
        sticky["month_date"] = prev["updated"][:7]
    day_cycle = 0
    last_ok = None  # epoch of last fully successful cycle
    print(f"apsystems_daemon: local ECU {ECU_IP}:{ECU_MODBUS_PORT} primary, "
          f"cloud fallback; -> {STATE} (hydrated {len(sticky)} keys)", flush=True)

    while True:
        now = local_now()
        day_str = now.strftime("%Y-%m-%d")
        day_mode = DAY_START_H <= now.hour < DAY_END_H
        status = "ok"
        error = ""
        source = ""
        try:
            # ── primary: local SunSpec Modbus (no quota, works at night) ──
            loc = fetch_local()
            source = "local"
            sticky.update(
                power_w=loc["power_w"],
                last_slot_time=now.strftime("%H:%M"),
                data_age_min=0,
            )
            for k in ("voltage_v", "va", "temp_c1", "temp_c2"):
                if loc[k] is not None:
                    sticky[k] = loc[k]
            if loc["today_kwh"] is not None or sticky.get("today_date") == day_str:
                record_today(sticky, loc["today_kwh"], day_str)
            elif sticky.get("today_date") != day_str:
                # new day, local accumulator not yet reporting
                sticky["today_date"] = day_str
                sticky["today_kwh"] = 0.0
            # cloud extras at low cadence (what Modbus doesn't expose)
            y_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            if sticky.get("yesterday_date") != y_str:
                yd = refresh_yesterday()
                if yd:
                    sticky["yesterday_date"], sticky["yesterday_kwh"] = yd
            if day_mode:
                day_cycle += 1
                if sticky.get("month_date") != now.strftime("%Y-%m") or day_cycle % SUMMARY_EVERY == 1:
                    sticky["inverters"] = fetch_inverter_power(day_str)
                    s = fetch_summary()
                    if s:
                        sticky["month_kwh"], sticky["year_kwh"], sticky["lifetime_kwh"] = s
                        sticky["month_date"] = now.strftime("%Y-%m")
            last_ok = time.time()
        except Exception as e1:  # noqa: BLE001 — fall back to the cloud
            # ── fallback: cloud minutely telemetry (quota-limited) ─────────
            try:
                if day_mode:
                    power_w, today_kwh, cur_hour, last_slot, age = fetch_minutely(day_str)
                else:
                    power_w, today_kwh, cur_hour, last_slot, age = 0, 0.0, 0.0, None, None
                source = "cloud"
                if day_mode:
                    day_cycle += 1
                    sticky.update(
                        power_w=power_w, current_hour_kwh=cur_hour,
                        last_slot_time=last_slot or "",
                        data_age_min=age if age is not None else -1,
                    )
                    record_today(sticky, today_kwh, day_str)
                    if day_cycle % SUMMARY_EVERY == 1:
                        sticky["inverters"] = fetch_inverter_power(day_str)
                else:
                    sticky.update(power_w=0)
                    record_today(sticky, None, day_str)
                y_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                if sticky.get("yesterday_date") != y_str:
                    yd = refresh_yesterday()
                    if yd:
                        sticky["yesterday_date"], sticky["yesterday_kwh"] = yd
                if sticky.get("month_date") != now.strftime("%Y-%m"):
                    s = fetch_summary()
                    if s:
                        sticky["month_kwh"], sticky["year_kwh"], sticky["lifetime_kwh"] = s
                        sticky["month_date"] = now.strftime("%Y-%m")
                last_ok = time.time()
            except urllib.error.HTTPError as e2:
                error = f"local: {e1}; cloud: http {e2.code}"
                status = "auth_error" if e2.code in (401, 403) else "error"
            except Exception as e2:  # noqa: BLE001
                error = f"local: {str(e1)[:80]}; cloud: {str(e2)[:80]}"
                status = "error"

        stale_min = int((time.time() - last_ok) / 60) if last_ok else 9999
        if status != "ok":
            print(f"cycle failed ({error}); serving sticky data "
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
            "source": source,
            "voltage_v": sticky.get("voltage_v"),
            "temp_c": sticky.get("temp_c1"),
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

        # quota (2005) backs off hard; busy (7002/7003) doubles one cycle
        if "2005" in error:
            print(f"quota exceeded (daily access limit); backing off "
                  f"{QUOTA_BACKOFF_SEC // 60} min", flush=True)
            time.sleep(QUOTA_BACKOFF_SEC)
        elif "7002" in error or "7003" in error:
            time.sleep(POLL_SEC * 2)
        else:
            time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
