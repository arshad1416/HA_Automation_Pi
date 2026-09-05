#!/usr/bin/env bash
# eth2 (Realtek r8152 USB adapter on the eero LAN, 192.168.0.102) watchdog.
#
# Why: on 2026-09-05 the adapter logged `r8152 eth2: Tx status -71`, reset itself,
# and came back receiving but never transmitting. HA lost every LAN integration
# for ~5 h and it looked like a router blackout from the Mac. The only software
# fix is a USB re-authorize of the device (nmcli bounce does nothing). See
# reference/climate-ai-tou-audit-2026-09-05.md §"LAN" and the memory note
# pi-usb-nic-tx-hang.
#
# Signature we act on, and ONLY this one: the gateway is unreachable out of eth2
# AND the tx_packets counter did not move while we tried. A dead gateway with a
# working NIC still increments tx (ARP/ICMP go out), so an eero reboot does not
# trigger a reset here. Two consecutive failures (timer runs every 2 min) before
# acting, and never more than one reset per 10 min.
#
# Runs as root from eth2-watchdog.timer. Test the no-reset branch by hand with an
# unreachable target:  sudo ETH2_WATCHDOG_GW=192.168.0.250 bash pi-config/eth2-watchdog.sh
set -u
IF=${ETH2_WATCHDOG_IF:-eth2}
GW=${ETH2_WATCHDOG_GW:-192.168.0.1}
STATE=/run/eth2-watchdog.fails
LAST=/run/eth2-watchdog.last-reset
TXF=/sys/class/net/$IF/statistics/tx_packets

[ -r "$TXF" ] || { logger -t eth2-watchdog "$IF missing"; exit 0; }
tx0=$(cat "$TXF")
if ping -c1 -W2 -I "$IF" "$GW" >/dev/null 2>&1; then rm -f "$STATE"; exit 0; fi
tx1=$(cat "$TXF")
if [ "$tx1" -gt "$tx0" ]; then
  # NIC transmits; the target is what is down. Not our problem.
  rm -f "$STATE"; exit 0
fi

n=$(( $(cat "$STATE" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$STATE"
[ "$n" -ge 2 ] || exit 0
now=$(date +%s); last=$(cat "$LAST" 2>/dev/null || echo 0)
if [ $((now - last)) -lt 600 ]; then
  logger -t eth2-watchdog "$IF still hung ($n fails) but last reset was $((now - last))s ago; waiting"
  exit 0
fi

# ponytail: resolve the USB device from the NIC so a port move does not break this.
usbdev=$(readlink -f "/sys/class/net/$IF/device/..")
[ -w "$usbdev/authorized" ] || { logger -t eth2-watchdog "cannot find authorized node under $usbdev"; exit 1; }
logger -t eth2-watchdog "$IF hung: no reply from $GW and tx frozen at $tx1 for $n checks; re-authorizing $(basename "$usbdev")"
echo 0 > "$usbdev/authorized"; sleep 4; echo 1 > "$usbdev/authorized"
echo "$now" > "$LAST"; rm -f "$STATE"
sleep 15
if ping -c1 -W2 -I "$IF" "$GW" >/dev/null 2>&1; then
  logger -t eth2-watchdog "$IF recovered"
else
  logger -t eth2-watchdog "$IF still unreachable after re-authorize; will retry in 10 min"
fi
