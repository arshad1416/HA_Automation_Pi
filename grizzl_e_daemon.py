#!/usr/bin/env python3
"""grizzl_e_daemon.py — single persistent connection to the Grizzl-E Smart /logs
stream (the endpoint serves ONE client at a time). Parses telemetry, accumulates
charging ENERGY and COST using Ontario ULO rates + Alectra (Hamilton/Horizon)
delivery charges, tracks sessions, and keeps a persistent per-day history.

Outputs:
  STATE file   (default /config/grizzl_e_state.json)  — read by HA command_line sensors
  HISTORY file (default /config/grizzl_e_history.json) — persistent per-day rollup

Stdlib only. Auto-reconnects. Atomic writes. Run via systemd (see grizzl-e-daemon.service).

Usage: grizzl_e_daemon.py [host] [state_file] [rates_file] [history_file]
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, date, timedelta

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.115"
STATE = sys.argv[2] if len(sys.argv) > 2 else "/config/grizzl_e_state.json"
RATES_FILE = sys.argv[3] if len(sys.argv) > 3 else "/config/grizzl_e_rates.json"
HISTORY = sys.argv[4] if len(sys.argv) > 4 else "/config/grizzl_e_history.json"

URL = "http://%s/logs" % HOST
START_THRESH_W = 100.0
STOP_THRESH_W = 50.0
WRITE_EVERY = 5.0
MAX_DT = 120.0  # ignore gaps longer than this (daemon downtime)

# ----------------------------------------------------------------------------- rates
def load_rates():
    try:
        with open(RATES_FILE) as f:
            r = json.load(f)
    except Exception:
        r = {}
    energy = r.get("ulo_energy_cents_kwh", {})
    energy.setdefault("overnight", 3.9)
    energy.setdefault("weekend_offpeak", 9.8)
    energy.setdefault("midpeak", 15.7)
    energy.setdefault("onpeak", 39.1)
    d = r.get("delivery", {})
    fixed = d.get("fixed_monthly_cad", {})
    var = d.get("variable_cents_kwh", {})
    fixed_monthly = float(fixed.get("service_charge", 33.32)) + float(fixed.get("regulatory_supply", 0.25))
    var_cents = float(var.get("transmission", 2.18)) + float(var.get("wholesale_market_service", 0.53)) + float(var.get("distribution", 0.033))
    line_loss = float(d.get("line_loss_pct_of_energy_charge", 3.79))
    mult = 1.0 + line_loss / 100.0
    # marginal all-in cents/kWh per period = (energy + line loss on energy + variable delivery)
    marginal = {p: energy[p] * mult + var_cents for p in energy}
    tz_name = r.get("timezone", "America/Toronto")
    tz = ZoneInfo(tz_name) if ZoneInfo else None
    return {
        "energy": energy,
        "marginal": marginal,
        "fixed_monthly": fixed_monthly,
        "var_cents": var_cents,
        "line_loss": line_loss,
        "tz": tz,
    }

RATES = load_rates()

# ----------------------------------------------------------------------------- holidays (Ontario / OEB)
def easter(y):
    a = y % 19
    b, c = divmod(y, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month = (h + l - 7 * m + 90) // 25
    day = (h + l - 7 * m + 33 * month + 19) % 32
    return date(y, month, day)

def nth_weekday(y, month, weekday, n):
    d = date(y, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))

def holidays(y):
    s = set()
    s.add(date(y, 1, 1))                       # New Year's Day
    s.add(nth_weekday(y, 2, 0, 3))             # Family Day (3rd Mon Feb)
    s.add(easter(y) - timedelta(days=2))       # Good Friday
    s.add(nth_weekday(y, 5, 0, 1) + timedelta(days=7 * 0))  # Victoria Day (Mon before May 25)
    # Victoria Day = last Monday on/before May 24
    vd = date(y, 5, 24)
    while vd.weekday() != 0:
        vd -= timedelta(days=1)
    s.add(vd)
    s.add(date(y, 7, 1))                       # Canada Day
    s.add(nth_weekday(y, 8, 0, 1))             # Civic Holiday (1st Mon Aug)
    s.add(nth_weekday(y, 9, 0, 1))             # Labour Day (1st Mon Sep)
    s.add(nth_weekday(y, 10, 0, 2))            # Thanksgiving (2nd Mon Oct)
    s.add(date(y, 12, 25))                     # Christmas
    s.add(date(y, 12, 26))                     # Boxing Day
    return s

_HOLIDAY_CACHE = {}
def is_holiday(d):
    if d.year not in _HOLIDAY_CACHE:
        _HOLIDAY_CACHE[d.year] = holidays(d.year)
    return d in _HOLIDAY_CACHE[d.year]

def rate_period(dt):
    h = dt.hour
    if h >= 23 or h < 7:
        return "overnight"
    if dt.weekday() >= 5 or is_holiday(dt.date()):
        return "weekend_offpeak"
    if 16 <= h < 21:
        return "onpeak"
    return "midpeak"

PERIOD_LABEL = {
    "overnight": "Ultra-Low Overnight",
    "weekend_offpeak": "Weekend Off-Peak",
    "midpeak": "Mid-Peak",
    "onpeak": "On-Peak",
}

# ----------------------------------------------------------------------------- state
state = {
    "power_w": 0.0, "charging": "off", "rssi_dbm": -99, "free_heap": -1, "disk_free_kb": -1,
    "updated": 0,
    "period": "midpeak", "period_label": "Mid-Peak", "rate_cents_kwh": 0.0,
    "total_energy_kwh": 0.0, "total_cost_cents": 0.0,
    "session_energy_kwh": 0.0, "session_cost_cents": 0.0, "session_start": None,
    "fixed_monthly_cad": RATES["fixed_monthly"],
}
history = {"days": {}}

def load_history():
    global history
    try:
        with open(HISTORY) as f:
            history = json.load(f)
        state["total_energy_kwh"] = float(history.get("total_energy_kwh", 0.0))
        state["total_cost_cents"] = float(history.get("total_cost_cents", 0.0))
        if "days" not in history:
            history["days"] = {}
    except Exception:
        history = {"days": {}, "total_energy_kwh": 0.0, "total_cost_cents": 0.0}

def atomic_write(path, obj):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except Exception:
        pass

def write_state():
    atomic_write(STATE, state)

def write_history():
    history["total_energy_kwh"] = state["total_energy_kwh"]
    history["total_cost_cents"] = state["total_cost_cents"]
    # prune to last 400 days
    days = history.get("days", {})
    if len(days) > 400:
        for k in sorted(days)[:-400]:
            del days[k]
    atomic_write(HISTORY, history)

# ----------------------------------------------------------------------------- accumulation
last_tick = [time.time()]
last_write = [0.0]
last_hist_write = [0.0]

def now_local():
    return datetime.now(RATES["tz"]) if RATES["tz"] else datetime.now()

def accumulate():
    now = time.time()
    dt_s = now - last_tick[0]
    last_tick[0] = now
    if dt_s <= 0 or dt_s > MAX_DT:
        return
    p = state["power_w"]
    was_charging = state["charging"] == "on"
    # session start / stop detection
    if p > START_THRESH_W and not was_charging:
        state["charging"] = "on"
        state["session_energy_kwh"] = 0.0
        state["session_cost_cents"] = 0.0
        state["session_start"] = int(now)
        was_charging = True
    elif p < STOP_THRESH_W and was_charging:
        state["charging"] = "off"
        state["session_start"] = None
        was_charging = False
    if not was_charging or p <= 0:
        return
    kwh = p * dt_s / 3_600_000.0
    nldt = now_local()
    period = rate_period(nldt)
    cents = kwh * RATES["marginal"][period]
    # totals
    state["total_energy_kwh"] += kwh
    state["total_cost_cents"] += cents
    state["session_energy_kwh"] += kwh
    state["session_cost_cents"] += cents
    # daily history
    dkey = nldt.date().isoformat()
    day = history["days"].setdefault(
        dkey, {"energy_kwh": 0.0, "cost_cents": 0.0,
               "by_period": {"overnight": 0.0, "weekend_offpeak": 0.0, "midpeak": 0.0, "onpeak": 0.0}})
    day["energy_kwh"] += kwh
    day["cost_cents"] += cents
    day["by_period"][period] = day["by_period"].get(period, 0.0) + kwh

# ----------------------------------------------------------------------------- log parsing
RE_POWER = re.compile(r"Current rate: ([0-9.]+) W")
RE_RSSI = re.compile(r"rssi: (-?[0-9]+)")
RE_HEAP = re.compile(r"Free heap: ([0-9]+)")
RE_DISK = re.compile(r"Disk usage:.*free ([0-9]+)")

def handle(line):
    m = RE_POWER.search(line)
    if m:
        state["power_w"] = float(m.group(1))
        return
    m = RE_RSSI.search(line)
    if m:
        state["rssi_dbm"] = int(m.group(1))
        return
    m = RE_HEAP.search(line)
    if m:
        state["free_heap"] = int(m.group(1))
        return
    m = RE_DISK.search(line)
    if m:
        state["disk_free_kb"] = int(m.group(1))
        return

def refresh_rate_info():
    nldt = now_local()
    period = rate_period(nldt)
    state["period"] = period
    state["period_label"] = PERIOD_LABEL[period]
    state["rate_cents_kwh"] = round(RATES["marginal"][period], 2)

def stream_once():
    req = urllib.request.Request(URL, headers={"User-Agent": "ha-grizzl/2.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        while True:
            raw = resp.readline()
            if not raw:
                break
            try:
                handle(raw.decode("utf-8", "ignore"))
            except Exception:
                pass
            accumulate()
            now = time.time()
            state["updated"] = int(now)
            refresh_rate_info()
            if now - last_write[0] >= WRITE_EVERY:
                write_state()
                last_write[0] = now
            if now - last_hist_write[0] >= 30.0:
                write_history()
                last_hist_write[0] = now

def main():
    load_history()
    refresh_rate_info()
    write_state()
    write_history()
    while True:
        try:
            stream_once()
        except Exception:
            pass
        time.sleep(5)

if __name__ == "__main__":
    main()
