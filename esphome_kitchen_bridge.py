#!/usr/bin/env python3
"""
ESPHome Kitchen mmWave → HA Bridge Daemon (v2 — with debounce)

Workaround for HA 2026.6.3 + Python 3.14 ESPHome integration bug where the
ESPHome integration's ReconnectLogic silently hangs and never connects to
the ESP32, leaving all kitchen_mmwave entities stuck at 'unknown'.

This script connects directly to the ESP32 via aioesphomeapi (which works
fine), subscribes to presence/moving_distance state changes, and pushes
those states into HA via the REST API. The existing kitchen occupancy
automation (automation.downstairs_occupancy_lighting) triggers on
input_boolean.kitchen_occupied_motion, so this bridge flips that boolean
to drive the full lighting automation.

v2 CHANGES:
- Debounce: presence going OFF waits 15s before pushing to HA. If presence
  comes back ON during that window, the OFF is cancelled. This prevents
  rapid on/off cycling that causes light flickering.
- The binary_sensor state in HA is still updated immediately (for UI feedback)
  but the input_boolean (which drives the automation) is debounced.

Runs as a daemon — auto-reconnects on disconnect, auto-retries on error.
"""
import asyncio
import json
import hashlib
import hmac
import base64
import time
import datetime
import logging
import signal
import sys
import os
import urllib.request
import urllib.error
from aioesphomeapi import APIClient

# --- Configuration ---
ESPHOME_HOST = "192.168.0.108"
ESPHOME_PORT = 6053
ESPHOME_PASSWORD = ""

HA_URL = "http://localhost:8123"
HA_AUTH_STORAGE = "/config/.storage/auth"

PRESENCE_ENTITY = "binary_sensor.kitchen_mmwave_presence_sensor_presence"
MOVING_DISTANCE_ENTITY = "sensor.kitchen_mmwave_presence_sensor_moving_distance"
OCCUPANCY_BOOLEAN = "input_boolean.kitchen_occupied_motion"
FAULT_ENTITY = "binary_sensor.kitchen_mmwave_radar_fault"

# Debounce: how long to wait after presence goes OFF before pushing the OFF to HA.
# The LD2420 radar can rapidly flip on/off when someone is stationary or at the
# edge of detection range. This grace period prevents the lights from flickering.
PRESENCE_OFF_DEBOUNCE_SECONDS = 15

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("esphome-bridge")

# --- HA JWT Auth ---
def sign_jwt():
    """Sign a short-lived JWT using HA's auth storage."""
    with open(HA_AUTH_STORAGE) as f:
        auth_data = json.load(f)
    tokens = auth_data.get("data", {}).get("refresh_tokens", [])
    llat = [t for t in tokens if t.get("token_type") == "long_lived_access_token"]
    if not llat:
        raise RuntimeError("No long-lived access tokens found in HA auth storage")
    llat = llat[-1]

    def b64url(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    now = int(time.time())
    header_b64 = b64url({"alg": "HS256", "typ": "JWT"})
    payload_b64 = b64url({"iss": llat["id"], "iat": now, "exp": now + 300})
    si = f"{header_b64}.{payload_b64}"
    sig = hmac.new(llat["jwt_key"].encode(), si.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{si}.{sig_b64}"

_jwt_token = None
_jwt_expiry = 0

def get_jwt():
    global _jwt_token, _jwt_expiry
    if _jwt_token and time.time() < _jwt_expiry - 30:
        return _jwt_token
    _jwt_token = sign_jwt()
    _jwt_expiry = time.time() + 240  # 4 min (token valid 5 min)
    return _jwt_token

# --- HA REST API helpers ---
def call_service(domain, service, data):
    """Call a HA service via REST API."""
    token = get_jwt()
    url = f"{HA_URL}/api/services/{domain}/{service}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 401:
            global _jwt_token, _jwt_expiry
            _jwt_token = None
            _jwt_expiry = 0
            return call_service(domain, service, data)
        log.error(f"Service call {domain}.{service} failed: HTTP {e.code}")
        return False
    except Exception as e:
        log.error(f"Service call {domain}.{service} failed: {e}")
        return False

def set_state(entity_id, state, attributes=None):
    """Set an entity state via REST API (forces state update in HA)."""
    token = get_jwt()
    url = f"{HA_URL}/api/states/{entity_id}"
    body = {"state": state}
    if attributes:
        body["attributes"] = attributes
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 401:
            global _jwt_token, _jwt_expiry
            _jwt_token = None
            _jwt_expiry = 0
            token = get_jwt()
            data2 = json.dumps(body).encode()
            req2 = urllib.request.Request(url, data=data2, method="POST",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req2, timeout=15) as r:
                    return r.status == 200
            except Exception as e2:
                log.error(f"set_state {entity_id} retry failed: {e2}")
                return False
        log.error(f"set_state {entity_id} failed: HTTP {e.code}")
        return False
    except Exception as e:
        log.error(f"set_state {entity_id} failed: {e}")
        return False

# --- ESPHome Bridge ---
class ESPHomeBridge:
    def __init__(self):
        self.client = None
        self.key_map = {}
        self.presence_key = None
        self.distance_key = None
        self.last_presence = None
        self.running = True
        self._off_debounce_task = None
        # UART fault detection
        self.firmware_key = None
        self.last_firmware = None
        self.last_fault = None
        self._connected_at = 0

    async def connect(self):
        """Connect to ESP32 and subscribe to state updates."""
        # Recreate client for fresh connection
        self.client = APIClient(ESPHOME_HOST, ESPHOME_PORT, ESPHOME_PASSWORD)
        log.info(f"Connecting to ESPHome at {ESPHOME_HOST}:{ESPHOME_PORT}...")
        await self.client.connect(login=True)
        log.info(f"Connected! API version: {self.client.api_version}")

        # Get entity list to map keys -> names
        entities, services = await self.client.list_entities_services()
        self.key_map = {e.key: e for e in entities}
        log.info(f"Found {len(entities)} entities")

        for e in entities:
            if e.object_id == "presence":
                self.presence_key = e.key
                log.info(f"  Presence key: {e.key} ({e.name})")
            elif e.object_id == "moving_distance":
                self.distance_key = e.key
                log.info(f"  Moving Distance key: {e.key} ({e.name})")
            elif e.object_id == "ld2420_firmware":
                self.firmware_key = e.key
                log.info(f"  Firmware key: {e.key} ({e.name})")

    def on_state(self, state):
        """Sync callback for ESPHome state updates. Schedules async handling."""
        asyncio.ensure_future(self._handle_state(state))

    async def _handle_state(self, state):
        """Process an ESPHome state update and push to HA."""
        entity = self.key_map.get(state.key)
        if not entity:
            return

        obj_id = entity.object_id
        val = getattr(state, "state", None)
        ts = datetime.datetime.now().strftime("%H:%M:%S")

        if obj_id == "presence":
            new_presence = "on" if val else "off"

            if new_presence == self.last_presence:
                return  # No change, ignore

            log.info(f"[{ts}] Presence: {self.last_presence} -> {new_presence} (raw={val})")
            self.last_presence = new_presence

            # Always update the binary_sensor state in HA immediately (for UI)
            set_state(PRESENCE_ENTITY, new_presence, {
                "device_class": "occupancy",
                "friendly_name": "Kitchen mmWave Presence Sensor Presence",
            })

            if new_presence == "on":
                # Cancel any pending OFF debounce
                if self._off_debounce_task and not self._off_debounce_task.done():
                    self._off_debounce_task.cancel()
                    log.info(f"[{ts}] Cancelled pending OFF debounce")

                # Immediately turn ON — no debounce needed for ON
                call_service("input_boolean", "turn_on",
                             {"entity_id": OCCUPANCY_BOOLEAN})
                log.info(f"[{ts}] -> input_boolean ON (lights should trigger)")

            else:
                # Don't turn OFF immediately — debounce with a grace period.
                # The LD2420 radar can flip off briefly when someone is still
                # in the room but momentarily stationary or at detection edge.
                # Cancel any previous debounce and start a new one.
                if self._off_debounce_task and not self._off_debounce_task.done():
                    self._off_debounce_task.cancel()

                self._off_debounce_task = asyncio.create_task(
                    self._debounced_off(ts)
                )

        elif obj_id == "moving_distance":
            dist_str = str(val)
            set_state(MOVING_DISTANCE_ENTITY, dist_str, {
                "unit_of_measurement": "cm",
                "device_class": "distance",
                "state_class": "measurement",
                "friendly_name": "Kitchen mmWave Presence Sensor Moving Distance",
            })

        elif obj_id == "ld2420_firmware":
            self.last_firmware = val

    async def _debounced_off(self, ts):
        """Wait PRESENCE_OFF_DEBOUNCE_SECONDS, then turn OFF the input_boolean.
        If presence comes back ON during the wait, this task is cancelled."""
        try:
            log.info(f"[{ts}] Presence OFF — debouncing {PRESENCE_OFF_DEBOUNCE_SECONDS}s...")
            await asyncio.sleep(PRESENCE_OFF_DEBOUNCE_SECONDS)
            # Still off after debounce — push it
            call_service("input_boolean", "turn_off",
                         {"entity_id": OCCUPANCY_BOOLEAN})
            log.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] -> input_boolean OFF (debounce expired)")
        except asyncio.CancelledError:
            log.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Debounce cancelled — presence came back")

    def check_uart_health(self):
        """Flag a dead LD2420 UART link (firmware unreadable) in HA + notify."""
        if time.time() - self._connected_at < 30:
            return  # grace period for firmware state to arrive after connect
        fw = self.last_firmware
        dead = fw is None or str(fw).strip().lower() in ("", "unknown", "nan", "none")
        if dead and self.last_fault is not True:
            self.last_fault = True
            log.error("UART FAULT: LD2420 firmware unreadable -- radar not communicating. "
                      "Power-cycle the sensor (unplug ~10s).")
            set_state(FAULT_ENTITY, "on", {"device_class": "problem",
                      "friendly_name": "Kitchen mmWave Radar Fault"})
            call_service("persistent_notification", "create", {
                "title": "Kitchen mmWave radar fault",
                "message": "The LD2420 radar stopped responding (firmware unreadable / UART dead). "
                           "Power-cycle the sensor (unplug ~10s) -- a software reboot will not fix it.",
                "notification_id": "kitchen_mmwave_uart_fault"})
            call_service("notify", "mobile_app_cph2655", {
                "message": "Kitchen mmWave radar fault -- power-cycle the sensor (unplug ~10s)."})
        elif not dead and self.last_fault is not False:
            self.last_fault = False
            log.info(f"UART OK: LD2420 firmware readable ({fw}).")
            set_state(FAULT_ENTITY, "off", {"device_class": "problem",
                      "friendly_name": "Kitchen mmWave Radar Fault"})
            call_service("persistent_notification", "dismiss",
                         {"notification_id": "kitchen_mmwave_uart_fault"})

    async def run(self):
        """Main loop: connect, subscribe, auto-reconnect."""
        while self.running:
            try:
                await self.connect()

                # Subscribe to state updates
                self.client.subscribe_states(self.on_state)
                log.info("Subscribed to state updates. Bridge is live.")
                log.info("Waiting for presence events...")
                self._connected_at = time.time()

                # Keep the connection alive + periodic UART health check
                last_health = 0.0
                while self.running:
                    await asyncio.sleep(1)
                    if time.time() - last_health >= 30:
                        last_health = time.time()
                        self.check_uart_health()

            except Exception as e:
                log.error(f"Connection error: {type(e).__name__}: {e}")
                log.info(f"Reconnecting in 10 seconds...")
                await asyncio.sleep(10)

    def stop(self):
        self.running = False
        log.info("Bridge stopping...")

async def main():
    bridge = ESPHomeBridge()

    # Handle SIGTERM/SIGINT for clean shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, bridge.stop)

    await bridge.run()

if __name__ == "__main__":
    asyncio.run(main())