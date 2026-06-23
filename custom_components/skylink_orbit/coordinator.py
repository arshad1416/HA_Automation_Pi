"""Data update coordinator for Skylink Orbit garage doors.

State updates are push-based via MQTT. The coordinator:
1. Builds the device list from config hub IDs
2. Connects MQTT and registers a state callback
3. When MQTT pushes a door state change, updates the device and notifies HA
"""

from __future__ import annotations

import logging
from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DoorDevice, OrbitApiError, OrbitAuthError, OrbitConnectionError, OrbitHomeAPI
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

SkyLinkOrbitConfigEntry: TypeAlias = "ConfigEntry[SkyLinkOrbitData]"


class SkyLinkOrbitData:
    """Runtime data stored in hass.data for a config entry."""

    def __init__(self, api: OrbitHomeAPI, coordinator: SkyLinkOrbitCoordinator) -> None:
        self.api = api
        self.coordinator = coordinator


class SkyLinkOrbitCoordinator(DataUpdateCoordinator[dict[str, DoorDevice]]):
    """Coordinator that manages MQTT connection and door state updates.

    State updates come via MQTT push (update/result topic), not polling.
    The coordinator timer still runs to retry MQTT connection if it drops.
    """

    config_entry: SkyLinkOrbitConfigEntry

    def __init__(self, hass: HomeAssistant, api: OrbitHomeAPI) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.api = api
        self._devices: dict[str, DoorDevice] = {}
        self._mqtt_started = False

        # Register MQTT state callback
        self.api.register_state_callback(self._on_door_state_update)

    def _on_door_state_update(self, hub_id: str, state: str) -> None:
        """Called from MQTT thread when a door state update arrives.

        Updates the device state and schedules a coordinator refresh
        so all entities pick up the new state.
        """
        device = self._devices.get(hub_id)
        if device is None:
            _LOGGER.debug("State update for unknown hub_id: %s", hub_id)
            return

        old_state = device.state
        device.state = state

        if old_state != state:
            _LOGGER.info(
                "Door %s state changed: %s -> %s",
                hub_id, old_state, state,
            )
            # Schedule HA entity update from the MQTT thread
            self.hass.loop.call_soon_threadsafe(
                self.async_set_updated_data, dict(self._devices)
            )

    async def _async_update_data(self) -> dict[str, DoorDevice]:
        """Called periodically. Builds devices on first run, retries MQTT if needed."""
        try:
            # First update: build device list from config
            if not self._devices:
                devices = self.api.get_devices()
                self._devices = {d.device_id: d for d in devices}
                _LOGGER.info(
                    "Loaded %d door(s): %s",
                    len(self._devices), list(self._devices.keys()),
                )

            # Connect/reconnect MQTT if needed
            if not self._mqtt_started or not self.api.mqtt_connected:
                try:
                    await self.api.connect_mqtt()
                    self._mqtt_started = True
                except Exception as err:
                    _LOGGER.warning("MQTT connection failed: %s", err)

        except OrbitAuthError as err:
            raise ConfigEntryAuthFailed(
                "Authentication expired, please re-enter credentials"
            ) from err
        except OrbitConnectionError as err:
            raise UpdateFailed(f"Cannot reach Skylink cloud: {err}") from err
        except OrbitApiError as err:
            raise UpdateFailed(f"API error: {err}") from err

        return self._devices
