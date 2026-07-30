#!/usr/bin/env python3
"""
Tuya Human Presence Sensor Bridge for Home Assistant.

Polls the Tuya Human Presence Sensor (protocol 3.5) via tinytuya and pushes
presence state changes to HA via the REST API into input_boolean.kitchen_tuya_presence.

This mirrors the esphome_kitchen_bridge.py pattern — LocalTuya doesn't support
protocol 3.5, so we poll directly and use the HA REST API.

Device: ebcda90e6979dc7bcelxmo @ 192.168.0.61
DP 101: presence state — "none" | "presence" | "small_move" | "large_move" | "peaceful"
"""

import json
import time
import hashlib
import hmac
import base64
import urllib.request
import urllib.error
import logging
import signal
import sys

import tinytuya

# --- Configuration ---
DEVICE_ID = "ebcda90e6979dc7bcelxmo"
DEVICE_IP = "192.168.0.61"
LOCAL_KEY = "BLc9WCkI'?XaYmMB"
PROTOCOL = 3.5
POLL_INTERVAL = 2  # seconds between polls
REPUSH_INTERVAL = 60  # re-push unchanged state every 60 s (stale-state failsafe)
HA_URL = "http://localhost:8123"
ENTITY_ID = "input_boolean.kitchen_tuya_presence"

# HA JWT auth — read from HA's own .storage/auth
# We generate a JWT from the long-lived access token stored in HA's auth file
# The same pattern used by esphome_kitchen_bridge.py

PRESENCE_VALUES = {"presence", "small_move", "large_move", "peaceful"}

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [TuyaBridge] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("TuyaBridge")


def get_ha_jwt():
    """Generate a JWT from HA's stored long-lived access token."""
    with open("/config/.storage/auth") as f:
        auth = json.load(f)
    tokens = auth["data"]["refresh_tokens"]
    llat = [t for t in tokens if t.get("token_type") == "long_lived_access_token"]
    if not llat:
        llat = [t for t in tokens if "jwt_key" in t]
    t = llat[-1]

    def b64(d):
        return base64.urlsafe_b64encode(
            json.dumps(d, separators=(",", ":")).encode()
        ).rstrip(b"=").decode()

    n = int(time.time())
    si = b64({"alg": "HS256", "typ": "JWT"}) + "." + b64(
        {"iss": t["id"], "iat": n, "exp": n + 86400}
    )
    jwt = si + "." + base64.urlsafe_b64encode(
        hmac.new(t["jwt_key"].encode(), si.encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return jwt


def set_ha_state(jwt, state):
    """Turn the HA input_boolean on or off via REST API."""
    action = "turn_on" if state == "on" else "turn_off"
    url = f"{HA_URL}/api/services/input_boolean/{action}"
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
    }
    data = json.dumps({"entity_id": ENTITY_ID}).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as e:
        log.error(f"HA API error: {e.code} {e.read().decode()[:200]}")
    except Exception as e:
        log.error(f"HA API error: {type(e).__name__}: {e}")


def main():
    log.info("Starting Tuya Human Presence Sensor bridge")
    log.info(f"Device: {DEVICE_ID} @ {DEVICE_IP} (protocol {PROTOCOL})")
    log.info(f"Target: {ENTITY_ID}")

    # Connect to the Tuya device
    device = tinytuya.Device(DEVICE_ID, DEVICE_IP, LOCAL_KEY, version=PROTOCOL)

    last_state = None
    last_push_time = 0.0
    jwt = get_ha_jwt()
    jwt_refresh_time = time.time()
    consecutive_errors = 0

    def refresh_jwt(signum=None, frame=None):
        nonlocal jwt, jwt_refresh_time
        jwt = get_ha_jwt()
        jwt_refresh_time = time.time()
        log.info("JWT refreshed")

    # Refresh JWT every 12 hours
    signal.signal(signal.SIGUSR1, refresh_jwt)

    log.info("Bridge running. Polling every %ds...", POLL_INTERVAL)

    while True:
        try:
            # Refresh JWT if older than 12 hours
            if time.time() - jwt_refresh_time > 43200:
                refresh_jwt()

            # Poll the device
            result = device.status()

            if result and "dps" in result:
                dps = result["dps"]
                presence = dps.get("101", "none")

                # Determine if presence is detected
                new_state = "on" if presence in PRESENCE_VALUES else "off"

                # Push to HA on change, and re-push periodically so a stale
                # input_boolean (e.g. reset to "off" by an HA restart) is
                # corrected within REPUSH_INTERVAL even without a change.
                if new_state != last_state:
                    log.info(
                        f"Presence changed: '{presence}' -> {new_state} "
                        f"(was: {last_state})"
                    )
                    set_ha_state(jwt, new_state)
                    last_state = new_state
                    last_push_time = time.time()
                elif time.time() - last_push_time > REPUSH_INTERVAL:
                    set_ha_state(jwt, new_state)
                    last_push_time = time.time()

                consecutive_errors = 0
            else:
                err = result.get("Error", "unknown") if isinstance(result, dict) else str(result)
                log.warning(f"Unexpected response: {err}")
                consecutive_errors += 1

        except Exception as e:
            consecutive_errors += 1
            log.error(f"Error #{consecutive_errors}: {type(e).__name__}: {e}")

            if consecutive_errors >= 10:
                log.warning("10 consecutive errors, reconnecting...")
                try:
                    device.close()
                except:
                    pass
                time.sleep(5)
                device = tinytuya.Device(
                    DEVICE_ID, DEVICE_IP, LOCAL_KEY, version=PROTOCOL
                )
                consecutive_errors = 0

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()