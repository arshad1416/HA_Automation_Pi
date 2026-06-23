"""
Orbit Home API client for Skylink G2 garage door openers.

This module is HA-independent so it can be tested standalone.

Protocol reverse-engineered from Orbit Home Android APK and mitmproxy captures:

REST API (account/hub management):
  - Endpoint: https://iot.skyhm.net:8444/skylinkhub_crm/skyhm_api_s.jsp
  - Commands via query parameter ?cmd=<command> AND REQ-CMD header
  - Custom headers: REQ-SIGNATURE, REQ-TIMESTAMP, REQ-DATA, REQ-CMD
  - Signature: MD5(timestamp + "+" + cmd + "+" + reqData + "+8uHDSF77ueRmLlKkl67").lower()
  - All requests are POST with JSON body

MQTT (door control and state):
  - Broker: ssl://34.214.223.70:1899
  - Auth: username=acc_no, password=account_password
  - Topics:
      Publish commands:  skylink/things/client/{acc_no}/desire
      State updates:     skylink/things/client/{acc_no}/update/result (subscribe)
  - GDO control payload:
      {"data":{"hub_id":"<id>","desired":{"mdev":{"ctrlgdo":{"cmd":0,"ts":"<ms>"}}}}}
  - State update payload (pushed by hub on door movement):
      {"data":{"hub_id":"<id>","reported":{"mdev":{"door":<int>,...}}}}
      door values: 0=open, 1=closed, other=moving
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import ssl as ssl_module
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Signing secret extracted from APK HeadInterceptor.intercept()
_SIGNING_SECRET = "+8uHDSF77ueRmLlKkl67"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OrbitApiError(Exception):
    """Base exception for Orbit Home API errors."""


class OrbitAuthError(OrbitApiError):
    """Authentication failed (bad credentials or expired token)."""


class OrbitConnectionError(OrbitApiError):
    """Could not reach the Orbit Home cloud service."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DoorDevice:
    """Represents a single garage door discovered from the API."""

    device_id: str          # hub_id (e.g., "rA8qM4QS")
    name: str               # display name (e.g., "Barn 8 foot")
    location: str = ""
    device_type: str = ""   # e.g., "GDO", "NOVA_A", "NOVA_B", "NVMini"
    state: str = "unknown"  # open, closed, opening, closing, stopped, unknown
    is_online: bool = True
    timezone: str = ""
    acc_no: str = ""
    position: str | None = None  # "A" or "B" for NOVA devices, None for GDO
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shared SSL context (no certificate verification - matches APK behaviour)
# Created at module level to avoid blocking the event loop.
# We use SSLContext() directly instead of create_default_context() because
# create_default_context() calls load_default_certs() which does disk I/O.
# ---------------------------------------------------------------------------

_SSL_CONTEXT = ssl_module.SSLContext(ssl_module.PROTOCOL_TLS_CLIENT)
_SSL_CONTEXT.check_hostname = False
_SSL_CONTEXT.verify_mode = ssl_module.CERT_NONE


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class OrbitHomeAPI:
    """Async client for the Orbit Home / Skylink cloud API.

    Uses REST API for authentication and device discovery, and MQTT for
    real-time door control and state monitoring.
    """

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._owns_session = session is None
        self._acc_no: str | None = None
        self._hub_ids: list[str] = []
        self._authenticated = False

        # MQTT
        self._mqtt_client: Any = None
        self._mqtt_connected = False
        self._state_callbacks: list[Callable] = []

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the HTTP session and MQTT connection."""
        if self._mqtt_client is not None:
            try:
                self._mqtt_client.loop_stop()
            except Exception:
                pass
            try:
                self._mqtt_client.disconnect()
            except Exception:
                pass
            self._mqtt_client = None
            self._mqtt_connected = False
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Signature / header generation (reverse-engineered from APK)
    # ------------------------------------------------------------------

    @staticmethod
    def _make_timestamp() -> str:
        return str(int(time.time() * 1000))

    @staticmethod
    def _make_signature(cmd: str, data: str, timestamp: str) -> str:
        """MD5(timestamp + "+" + cmd + "+" + reqData + "+8uHDSF77ueRmLlKkl67").lower()"""
        raw = f"{timestamp}+{cmd}+{data}{_SIGNING_SECRET}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest().lower()

    def _build_headers(self, cmd: str, req_data: str) -> dict[str, str]:
        timestamp = self._make_timestamp()
        return {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US;q=1",
            "User-Agent": "Orbit/3.4 (iPhone; iOS 18.3; Scale/3.00)",
            "Connection": "keep-alive",
            "REQ-CMD": cmd,
            "REQ-DATA": req_data,
            "REQ-TIMESTAMP": timestamp,
            "REQ-SIGNATURE": self._make_signature(cmd, req_data, timestamp),
        }

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------

    async def _request(
        self,
        cmd: str,
        json_body: dict[str, Any] | None = None,
        req_data: str | None = None,
    ) -> dict[str, Any]:
        """POST to the Skylink API endpoint.  Returns the parsed JSON dict."""
        if req_data is None:
            req_data = self._username

        session = await self._get_session()
        url = f"{self._base_url}?cmd={cmd}"
        headers = self._build_headers(cmd, req_data)
        _LOGGER.debug("API >>> POST %s  headers=%s", url, {k: v for k, v in headers.items() if k != "REQ-SIGNATURE"})

        body_text = ""
        try:
            async with session.post(
                url,
                json=json_body,
                headers=headers,
                ssl=_SSL_CONTEXT,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                body_text = await resp.text()
                _LOGGER.debug("API <<< %s  HTTP %s  body[:%d]=%s", cmd, resp.status, len(body_text), body_text[:300])

                if resp.status >= 400:
                    raise OrbitApiError(
                        f"HTTP {resp.status} for {cmd}: {body_text[:200]}"
                    )

                # --- Parse JSON robustly ---
                data = self._parse_json(body_text, cmd)

                # --- Check API-level result code ---
                result_code = data.get("result")
                if result_code is not None and str(result_code) not in ("0", "00"):
                    msg = data.get("message", "")
                    _LOGGER.warning(
                        "API error for cmd=%s  result=%s  message=%s  body=%s",
                        cmd, result_code, msg, body_text[:300],
                    )
                    if str(result_code) == "25":
                        raise OrbitAuthError(f"Invalid signature (result={result_code})")
                    raise OrbitApiError(f"API error result={result_code}: {msg}")

                return data

        except (OrbitApiError, OrbitAuthError, OrbitConnectionError):
            raise
        except aiohttp.ClientError as err:
            raise OrbitConnectionError(f"Connection error: {err}") from err
        except asyncio.TimeoutError as err:
            raise OrbitConnectionError("Request timed out") from err
        except Exception as err:
            # Catch-all: log everything we know and wrap it
            _LOGGER.error(
                "Unexpected error for cmd=%s  body=%s  error=%s: %s",
                cmd, body_text[:500], type(err).__name__, err,
            )
            raise OrbitApiError(f"Unexpected error for {cmd}: {err}") from err

    @staticmethod
    def _parse_json(text: str, cmd: str) -> dict[str, Any]:
        """Parse the server response as JSON.

        The Skylink server returns non-standard JSON in some cases:
          - Leading whitespace/newlines before the JSON object
          - Bare numbers with leading zeros, e.g. "result":00  (invalid JSON)
        We fix these before parsing.
        """
        import re

        # Strip BOM and whitespace
        cleaned = text.strip()
        if cleaned.startswith("\ufeff"):
            cleaned = cleaned[1:].strip()

        if not cleaned:
            raise OrbitApiError(f"Empty response body for {cmd}")

        # Fix non-standard JSON: bare numbers with leading zeros
        # e.g.  "result":00,  ->  "result":"00",
        #        "result":00}  ->  "result":"00"}
        cleaned = re.sub(r':(0\d+)([,}\]\s])', r':"\1"\2', cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as err:
            _LOGGER.error(
                "JSON parse failed for cmd=%s at pos %d.  "
                "Raw body (%d chars, repr): %r",
                cmd, err.pos, len(text), text[:500],
            )
            raise OrbitApiError(
                f"Server returned non-JSON for {cmd} (pos {err.pos}): {text[:80]!r}"
            ) from err

        if not isinstance(data, dict):
            raise OrbitApiError(f"Expected dict for {cmd}, got {type(data).__name__}")

        return data

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self) -> dict[str, Any]:
        """Log in via cmd=act_login.

        Real server response:
          {"result":00,"message":"Success","acc_no":"8003105701",
           "alias_name":"Brad","head_portrait":""}
        Note: result:00 (leading-zero bare number) is fixed by _parse_json.
        _request() already checks result != "00" and raises, so if we get
        here the login succeeded.
        """
        payload = {
            "app_sys": "apns",
            "username": self._username,
            "password": self._password,
            "app_brand": "00",
        }

        _LOGGER.info("Authenticating as %s against %s", self._username, self._base_url)

        try:
            data = await self._request(
                cmd="act_login",
                json_body=payload,
                req_data=self._username,
            )
        except OrbitConnectionError:
            raise
        except OrbitApiError as err:
            raise OrbitAuthError(f"Login failed: {err}") from err

        # _request() already verified result=="00" (success).
        # Grab acc_no from login response if available.
        acc_no = data.get("acc_no", "")
        if acc_no and not self._acc_no:
            self._acc_no = acc_no
            _LOGGER.info("Got acc_no from login: %s", acc_no)

        self._authenticated = True
        _LOGGER.info(
            "Authenticated as %s  acc_no=%s  alias=%s",
            self._username, self._acc_no, data.get("alias_name", ""),
        )
        return data

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def get_devices(self) -> list[DoorDevice]:
        """Build device list from configured hub IDs.

        We create DoorDevice objects directly from config since the hub_add
        REST command returns result=91. Device names default to the hub_id
        and can be renamed in the HA UI.
        """
        if not self._hub_ids:
            _LOGGER.warning("No hub IDs configured.")
            return []

        doors: list[DoorDevice] = []
        for hub_id in self._hub_ids:
            doors.append(DoorDevice(
                device_id=hub_id,
                name=f"Garage Door {hub_id}",
                device_type="GDO",
                state="unknown",
                is_online=True,
                acc_no=self._acc_no or "",
            ))

        _LOGGER.info("Created %d door(s): %s", len(doors), [d.device_id for d in doors])
        return doors

    def set_hub_ids(self, hub_ids: list[str]) -> None:
        self._hub_ids = list(hub_ids)

    def set_acc_no(self, acc_no: str) -> None:
        self._acc_no = acc_no

    # ------------------------------------------------------------------
    # MQTT connection and state handling
    #
    # State updates arrive on: skylink/things/client/{acc_no}/update/result
    # Payload format (confirmed via MQTT sniffer):
    #   {"data":{"hub_id":"rA8qM4QS","reported":{"mdev":{
    #       "door": 0,          <-- 0=closed, 1=open, 4=moving
    #       "autoclose_en": 0,
    #       "errno": 0,
    #       "rssi": -53,
    #       "ssid": "...",
    #       "firstdoor": {"door": 0},
    #       "fw": {"type":"1","ver":"...","ver_gdo":"..."}
    #   }}}}
    #
    # The "get" topic does NOT return responses. State is push-only.
    # ------------------------------------------------------------------

    # Door state mapping from numeric MQTT values to HA state strings
    # Confirmed by user testing: 0=open, 1=closed
    # Any other value (2, 3, 4, etc.) = door is in motion
    _DOOR_STATE_MAP: dict[int, str] = {
        0: "open",
        1: "closed",
    }
    _DOOR_STATE_DEFAULT = "opening"  # any unmapped value = in motion

    def _get_mqtt_topics(self) -> dict[str, str]:
        acc = self._acc_no or ""
        base = "skylink/things/client"
        return {
            "desire": f"{base}/{acc}/desire",
            "update_result": f"{base}/{acc}/update/result",
        }

    async def connect_mqtt(self) -> None:
        """Connect to ssl://34.214.223.70:1899."""
        if self._mqtt_connected:
            return

        if not self._acc_no:
            raise OrbitApiError("Cannot connect MQTT without acc_no -- authenticate first")

        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            raise OrbitApiError("paho-mqtt not installed")

        client_id = f"{self._acc_no}_{random.randint(100, 999)}"
        _LOGGER.info("MQTT connecting: broker=34.214.223.70:1899 client_id=%s", client_id)

        # Handle paho-mqtt 1.x vs 2.x API change
        try:
            from paho.mqtt.enums import CallbackAPIVersion
            self._mqtt_client = mqtt.Client(
                CallbackAPIVersion.VERSION1,
                client_id=client_id,
                protocol=mqtt.MQTTv311,
            )
        except ImportError:
            self._mqtt_client = mqtt.Client(
                client_id=client_id,
                protocol=mqtt.MQTTv311,
            )

        self._mqtt_client.username_pw_set(
            username=self._acc_no,
            password=self._password,
        )

        self._mqtt_client.tls_set_context(_SSL_CONTEXT)
        self._mqtt_client.tls_insecure_set(True)

        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_message = self._on_mqtt_message
        self._mqtt_client.on_disconnect = self._on_mqtt_disconnect

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._mqtt_client.connect("34.214.223.70", 1899, keepalive=30),
        )
        self._mqtt_client.loop_start()

        # Wait up to 5 seconds for the connection callback
        for _ in range(50):
            if self._mqtt_connected:
                break
            await asyncio.sleep(0.1)

        if not self._mqtt_connected:
            _LOGGER.warning("MQTT connection not confirmed within 5 s timeout")

    def _on_mqtt_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            _LOGGER.info("MQTT connected successfully")
            self._mqtt_connected = True
            topics = self._get_mqtt_topics()
            # Only subscribe to update/result -- state is push-only
            client.subscribe(topics["update_result"], qos=0)
            _LOGGER.info("MQTT subscribed: %s", topics["update_result"])
        else:
            rc_map = {1: "Bad protocol", 2: "Client ID rejected", 3: "Server unavailable",
                      4: "Bad credentials", 5: "Not authorised"}
            _LOGGER.error("MQTT connect failed: rc=%d (%s)", rc, rc_map.get(rc, "unknown"))

    def _on_mqtt_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handle incoming MQTT state update messages.

        Expected payload:
            {"data":{"hub_id":"...","reported":{"mdev":{"door":0,...}}}}
        """
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            _LOGGER.debug("MQTT <<< %s: %s", msg.topic, payload)

            # Parse hub_id and door state from the real payload format
            data = payload.get("data", {})
            hub_id = data.get("hub_id", "")
            reported = data.get("reported", {})
            mdev = reported.get("mdev", {}) if isinstance(reported, dict) else {}

            if hub_id and isinstance(mdev, dict) and "door" in mdev:
                door_val = mdev["door"]
                state = self._DOOR_STATE_MAP.get(
                    door_val, self._DOOR_STATE_DEFAULT
                )
                if door_val not in self._DOOR_STATE_MAP:
                    _LOGGER.info(
                        "MQTT unmapped door value: hub=%s door=%s -> treating as %s",
                        hub_id, door_val, state,
                    )
                _LOGGER.info(
                    "MQTT state update: hub=%s door=%s -> %s",
                    hub_id, door_val, state,
                )

                # Notify all registered callbacks (coordinator listens here)
                for cb in self._state_callbacks:
                    try:
                        cb(hub_id, state)
                    except Exception:
                        _LOGGER.exception("MQTT state callback error")
            else:
                _LOGGER.debug("MQTT message without door state: hub=%s data=%s", hub_id, data)

        except Exception:
            _LOGGER.exception("Error processing MQTT message on %s", msg.topic)

    def _on_mqtt_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        self._mqtt_connected = False
        if rc != 0:
            _LOGGER.warning("MQTT disconnected unexpectedly: rc=%d", rc)
        else:
            _LOGGER.debug("MQTT disconnected cleanly")

    def register_state_callback(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for door state updates.

        Callback signature: callback(hub_id: str, state: str)
        State values: "open", "closed", "opening", "unknown"
        """
        self._state_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Door commands via MQTT
    # ------------------------------------------------------------------

    async def toggle_door(self, hub_id: str, position: str | None = None) -> None:
        """Send GDO toggle via MQTT desire topic."""
        if not self._mqtt_connected:
            await self.connect_mqtt()

        gdo_cmd: dict[str, Any] = {"cmd": 0, "ts": str(int(time.time() * 1000))}
        if position:
            gdo_cmd["position"] = position

        payload = {"data": {"hub_id": hub_id, "desired": {"mdev": {"ctrlgdo": gdo_cmd}}}}
        topic = self._get_mqtt_topics()["desire"]
        payload_str = json.dumps(payload, separators=(",", ":"))

        _LOGGER.info("MQTT >>> %s: %s", topic, payload_str)

        if self._mqtt_client:
            self._mqtt_client.publish(topic, payload_str, qos=0)
        else:
            raise OrbitApiError("MQTT client not connected")

    async def open_door(self, hub_id: str, position: str | None = None) -> None:
        await self.toggle_door(hub_id, position)

    async def close_door(self, hub_id: str, position: str | None = None) -> None:
        await self.toggle_door(hub_id, position)

    async def stop_door(self, hub_id: str, position: str | None = None) -> None:
        await self.toggle_door(hub_id, position)

    @property
    def mqtt_connected(self) -> bool:
        """Return True if MQTT is connected."""
        return self._mqtt_connected
