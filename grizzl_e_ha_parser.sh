#!/usr/bin/env bash
# grizzl_e_ha_parser.sh — READ-ONLY Home Assistant feeder for the Grizzl-E Smart.
#
# Samples the charger's live /logs stream and emits a single JSON object with the
# latest telemetry. GET only; changes nothing on the device.
#
# Output JSON keys:
#   power_w      (float)  latest "Current rate" in watts        [0.0 if unseen]
#   charging     (string) "on" if power_w > THRESHOLD_W else "off"
#   rssi_dbm     (int)    latest Wi-Fi RSSI                     [-99 if unseen]
#   free_heap    (int)    latest free heap bytes                [-1 if unseen]
#   disk_free_kb (int)    latest free disk (KB)                 [-1 if unseen]
#
# Usage: grizzl_e_ha_parser.sh [host] [window_seconds]
set -u

HOST="${1:-192.168.0.115}"
WINDOW="${2:-14}"                 # capture window; power line repeats ~every 11s
THRESHOLD_W=100                   # watts above which we call it "charging"
URL="http://${HOST}/logs"

# Capture a bounded window of the endless log stream.
LOG="$(curl -s --max-time "$WINDOW" "$URL" 2>/dev/null)"

last_match() { printf '%s\n' "$LOG" | grep -E "$1" | tail -n1; }

# --- charging power (W) ---
POWER_LINE="$(last_match 'Current rate: [0-9.]+ W')"
POWER="$(printf '%s' "$POWER_LINE" | grep -oE '[0-9]+\.[0-9]+' | tail -n1)"
[ -z "${POWER:-}" ] && POWER="0.0"

# --- charging state ---
CHARGING="$(awk -v p="$POWER" -v t="$THRESHOLD_W" 'BEGIN{print (p>t)?"on":"off"}')"

# --- Wi-Fi RSSI (dBm) ---
RSSI_LINE="$(last_match 'rssi: -?[0-9]+')"
RSSI="$(printf '%s' "$RSSI_LINE" | grep -oE '\-?[0-9]+' | tail -n1)"
[ -z "${RSSI:-}" ] && RSSI="-99"

# --- free heap (bytes) ---
HEAP_LINE="$(last_match 'Free heap: [0-9]+')"
HEAP="$(printf '%s' "$HEAP_LINE" | grep -oE 'Free heap: [0-9]+' | grep -oE '[0-9]+')"
[ -z "${HEAP:-}" ] && HEAP="-1"

# --- free disk (KB) ---
DISK_LINE="$(last_match 'Disk usage:.*free [0-9]+')"
DISK="$(printf '%s' "$DISK_LINE" | grep -oE 'free [0-9]+' | grep -oE '[0-9]+')"
[ -z "${DISK:-}" ] && DISK="-1"

printf '{"power_w": %s, "charging": "%s", "rssi_dbm": %s, "free_heap": %s, "disk_free_kb": %s}\n' \
  "$POWER" "$CHARGING" "$RSSI" "$HEAP" "$DISK"
