#!/usr/bin/env python3
"""grizzl_e_daemon.py — single persistent connection to the Grizzl-E Smart /logs
stream. The charger's /logs endpoint serves only ONE client at a time, so this
daemon holds the single connection, parses telemetry, and writes a local JSON
state file that Home Assistant sensors read (instant, no per-poll charger hit).

Stdlib only. Auto-reconnects. Writes atomically. Run in background via nohup.

Usage: grizzl_e_daemon.py [host] [state_file]
"""
import json
import os
import re
import sys
import time
import urllib.request

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.115"
STATE = sys.argv[2] if len(sys.argv) > 2 else "/config/grizzl_e_state.json"
URL = "http://%s/logs" % HOST
THRESHOLD_W = 100.0
WRITE_EVERY = 5.0  # seconds between state-file writes

state = {
    "power_w": 0.0,
    "charging": "off",
    "rssi_dbm": -99,
    "free_heap": -1,
    "disk_free_kb": -1,
    "updated": 0,
}

RE_POWER = re.compile(r"Current rate: ([0-9.]+) W")
RE_RSSI = re.compile(r"rssi: (-?[0-9]+)")
RE_HEAP = re.compile(r"Free heap: ([0-9]+)")
RE_DISK = re.compile(r"Disk usage:.*free ([0-9]+)")


def write_state():
    tmp = STATE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE)
    except Exception:
        pass


def handle(line):
    m = RE_POWER.search(line)
    if m:
        p = float(m.group(1))
        state["power_w"] = p
        state["charging"] = "on" if p > THRESHOLD_W else "off"
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


def stream_once():
    req = urllib.request.Request(URL, headers={"User-Agent": "ha-grizzl/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        last_write = 0.0
        while True:
            raw = resp.readline()
            if not raw:
                break  # server closed
            try:
                handle(raw.decode("utf-8", "ignore"))
            except Exception:
                pass
            now = time.time()
            state["updated"] = int(now)
            if now - last_write >= WRITE_EVERY:
                write_state()
                last_write = now


def main():
    write_state()
    while True:
        try:
            stream_once()
        except Exception:
            pass
        time.sleep(5)  # backoff before reconnect


if __name__ == "__main__":
    main()
