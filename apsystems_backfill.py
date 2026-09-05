#!/usr/bin/env python3
"""apsystems_backfill.py — one-shot downloader of the FULL APsystems production
history into a local JSON archive (default /opt/homeassistant/apsystems_history.json).

Grabs every level the cloud still holds:
  yearly    (lifetime)            -> meta + "yearly"
  monthly   per year              -> "monthly"
  daily     per month             -> "daily"        {date: kWh}
  hourly    per day               -> "hourly"       {date: [24 floats]}
  minutely  per day (ECU, 5-min)  -> "minutely"     {date: {time[], power[], energy[]}}

Retention observed 2026-09-05 (system commissioned 2024): daily/monthly/yearly
cover the full lifetime; hourly/minutely start 2025-01-01. Days the API no
longer has are simply absent from hourly/minutely (code 1001 = "no data").

Auth: same signed GETs as apsystems_daemon.py; credentials from the
environment (APS_APP_ID / APS_APP_SECRET / APS_SYSTEM_ID / APS_ECU_ID) —
see pi-config/apsystems-solar.service.

Politeness: ~1 call/s; 7002/7003 (busy) backs off 30 s and retries the same
item (max 5). Checkpoints accumulate OUTSIDE the repo
(~/.apsystems_backfill_checkpoint.json) every 30 days so an interrupted run
can resume with --resume; the final archive is written atomically once at the
end (keeps the git auto-sync from committing a dozen growing half-files).

Usage: apsystems_backfill.py [out_file] [--resume]
"""
import calendar
import json
import os
import sys
import time
from datetime import date, timedelta

import base64
import hashlib
import hmac
import urllib.error
import urllib.request
import uuid

OUT = "/opt/homeassistant/apsystems_history.json"
if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
    OUT = sys.argv[1]
RESUME = "--resume" in sys.argv
CHECKPOINT = os.path.expanduser("~/.apsystems_backfill_checkpoint.json")

BASE_URL = "https://api.apsystemsema.com:9282"
CODE_OK, CODE_NO_DATA, CODE_BUSY = 0, 1001, (7002, 7003)
PAUSE_SEC = 0.8
CHECKPOINT_EVERY = 30  # days of per-day fetches


def _env(name):
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"missing env var {name}")
    return v


APP_ID, APP_SECRET = _env("APS_APP_ID"), _env("APS_APP_SECRET")
SYSTEM_ID, ECU_ID = _env("APS_SYSTEM_ID"), _env("APS_ECU_ID")


def api_get(path):
    rp = path.split("/")[-1].split("?")[0]
    ts = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    sig = base64.b64encode(
        hmac.new(APP_SECRET.encode(),
                 f"{ts}/{nonce}/{APP_ID}/{rp}/GET/HmacSHA256".encode(),
                 hashlib.sha256).digest()
    ).decode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"X-CA-AppId": APP_ID, "X-CA-Timestamp": ts, "X-CA-Nonce": nonce,
                 "X-CA-Signature-Method": "HmacSHA256", "X-CA-Signature": sig},
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                d = json.loads(resp.read().decode())
            if d.get("code") in CODE_BUSY and attempt < 5:
                print(f"  busy ({d['code']}) — backing off 30s", flush=True)
                time.sleep(30)
                continue
            return d
        except urllib.error.HTTPError as e:
            if attempt < 5:
                print(f"  HTTP {e.code} — retry in 15s", flush=True)
                time.sleep(15)
                continue
            raise
    return {"code": -1}


def month_days(ym):
    y, m = map(int, ym.split("-"))
    return calendar.monthrange(y, m)[1]


def main():
    archive = {"meta": {}, "yearly": [], "monthly": {}, "daily": {},
               "hourly": {}, "minutely": {}}
    if RESUME and os.path.exists(CHECKPOINT):
        with open(CHECKPOINT) as f:
            archive = json.load(f)
        print(f"resumed checkpoint: {len(archive['daily'])} days of daily, "
              f"{len(archive['minutely'])} of minutely", flush=True)

    # ── yearly (lifetime) ────────────────────────────────────────────────
    d = api_get(f"/user/api/v2/systems/energy/{SYSTEM_ID}?energy_level=yearly")
    yearly = [float(v or 0) for v in (d.get("data") or [])] if d.get("code") == CODE_OK else []
    archive["yearly"] = yearly
    if not yearly:
        sys.exit("yearly fetch failed — aborting")
    first_year = date.today().year - len(yearly) + 1
    print(f"yearly: {dict(zip(range(first_year, first_year + len(yearly)), yearly))}", flush=True)

    # ── monthly per year -> find first producing month ───────────────────
    today = date.today()
    commission = date(today.year, today.month, 1)
    for y in range(first_year, today.year + 1):
        time.sleep(PAUSE_SEC)
        d = api_get(f"/user/api/v2/systems/energy/{SYSTEM_ID}?energy_level=monthly&date_range={y}")
        if d.get("code") != CODE_OK:
            print(f"monthly {y}: code {d.get('code')} — skipped", flush=True)
            continue
        months = [float(v or 0) for v in (d.get("data") or [])]
        archive["monthly"][str(y)] = months
        nz = [i for i, kwh in enumerate(months) if kwh > 0]
        if nz:
            first_producing = date(y, nz[0] + 1, 1)
            if first_producing < commission:
                commission = first_producing
    print(f"commissioned: {commission:%Y-%m}", flush=True)

    # ── daily per month ──────────────────────────────────────────────────
    ym = commission
    while ym <= today:
        yms = f"{ym:%Y-%m}"
        if not any(k.startswith(yms) for k in archive["daily"]):
            time.sleep(PAUSE_SEC)
            d = api_get(f"/user/api/v2/systems/energy/{SYSTEM_ID}"
                        f"?energy_level=daily&date_range={yms}")
            if d.get("code") == CODE_OK:
                for i, kwh in enumerate(float(v or 0) for v in (d.get("data") or [])):
                    archive["daily"][f"{yms}-{i + 1:02d}"] = round(kwh, 3)
            else:
                print(f"daily {yms}: code {d.get('code')}", flush=True)
        ym = date(ym.year + (ym.month == 12), ym.month % 12 + 1, 1)

    # ── hourly + minutely per day (only what retention still holds) ──────
    day = commission
    fetched_days = 0
    total_days = (today - commission).days + 1
    while day <= today:
        ds = day.isoformat()
        if ds not in archive["minutely"] or ds not in archive["hourly"]:
            time.sleep(PAUSE_SEC)
            d = api_get(f"/user/api/v2/systems/energy/{SYSTEM_ID}"
                        f"?energy_level=hourly&date_range={ds}")
            if d.get("code") == CODE_OK:
                archive["hourly"][ds] = [round(float(v or 0), 3) for v in (d.get("data") or [])]
            time.sleep(PAUSE_SEC)
            d = api_get(f"/user/api/v2/systems/{SYSTEM_ID}/devices/ecu/energy/{ECU_ID}"
                        f"?energy_level=minutely&date_range={ds}")
            if d.get("code") == CODE_OK:
                data = d.get("data") or {}
                if data.get("time"):
                    archive["minutely"][ds] = {
                        "time": data.get("time"),
                        "power": [int(float(p or 0)) for p in (data.get("power") or [])],
                        "energy": [round(float(e or 0), 4) for e in (data.get("energy") or [])],
                    }
        fetched_days += 1
        if fetched_days % 25 == 0:
            print(f"  {fetched_days}/{total_days} days "
                  f"({ds}, minutely so far: {len(archive['minutely'])})", flush=True)
        if fetched_days % CHECKPOINT_EVERY == 0:
            with open(CHECKPOINT + ".tmp", "w") as f:
                json.dump(archive, f)
            os.replace(CHECKPOINT + ".tmp", CHECKPOINT)
        day += timedelta(days=1)

    # ── finalize ─────────────────────────────────────────────────────────
    days = sorted(k for k in archive["daily"] if archive["daily"][k] is not None)
    archive["meta"] = {
        "system_id": SYSTEM_ID, "ecu_id": ECU_ID,
        "capacity_kw": 11.44,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "daily_days": len(days),
        "hourly_days": len(archive["hourly"]),
        "minutely_days": len(archive["minutely"]),
        "daily_total_kwh": round(sum(v for v in archive["daily"].values() if v), 2),
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(archive, f)
        f.write("\n")
    os.replace(tmp, OUT)
    if os.path.exists(CHECKPOINT):
        os.remove(CHECKPOINT)

    # ── summary ──────────────────────────────────────────────────────────
    print(json.dumps(archive["meta"], indent=2))
    best = max(archive["daily"].items(), key=lambda kv: kv[1] or 0)
    print(f"best day: {best[0]} = {best[1]} kWh")
    print(f"archive: {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
