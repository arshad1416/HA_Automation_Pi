"""Garage door cover entities for Skylink Orbit."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DoorDevice, OrbitApiError
from .const import (
    DOMAIN,
    DOOR_STATE_CLOSED,
    DOOR_STATE_CLOSING,
    DOOR_STATE_OPEN,
    DOOR_STATE_OPENING,
    DOOR_STATE_STOPPED,
)
from .coordinator import SkyLinkOrbitConfigEntry, SkyLinkOrbitCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyLinkOrbitConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Skylink Orbit cover entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: SkyLinkOrbitCoordinator = data.coordinator

    entities = [
        SkyLinkOrbitGarageDoor(coordinator, device_id, entry)
        for device_id in coordinator.data
    ]

    async_add_entities(entities, update_before_add=False)


class SkyLinkOrbitGarageDoor(
    CoordinatorEntity[SkyLinkOrbitCoordinator], CoverEntity
):
    """A single Skylink garage door represented as a HA cover entity.

    The Skylink GDO only supports a toggle command (no separate open/close).
    All three HA commands (open, close, stop) send the same MQTT toggle.
    """

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    _attr_has_entity_name = True
    _attr_name = None  # Use device name as entity name

    def __init__(
        self,
        coordinator: SkyLinkOrbitCoordinator,
        device_id: str,
        entry: SkyLinkOrbitConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}"

    # ------------------------------------------------------------------
    # Device info (groups entities under one device in the UI)
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        door = self._door
        device_type = door.device_type if door else "GDO"
        model = f"Skylink {device_type}" if device_type else "Skylink G2"
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=door.name if door else f"Skylink Door {self._device_id[:8]}",
            manufacturer="Skylink",
            model=model,
        )

    # ------------------------------------------------------------------
    # State properties
    # ------------------------------------------------------------------

    @property
    def _door(self) -> DoorDevice | None:
        """Get this door's data from the coordinator."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        """Return True if the coordinator has data and the door is online."""
        if not super().available:
            return False
        door = self._door
        return door is not None and door.is_online

    @property
    def is_closed(self) -> bool | None:
        """Return True if the door is fully closed."""
        door = self._door
        if door is None:
            return None
        if door.state == DOOR_STATE_CLOSED:
            return True
        if door.state in (DOOR_STATE_OPEN, DOOR_STATE_OPENING, DOOR_STATE_CLOSING, DOOR_STATE_STOPPED):
            return False
        return None  # unknown

    @property
    def is_opening(self) -> bool:
        door = self._door
        return door is not None and door.state == DOOR_STATE_OPENING

    @property
    def is_closing(self) -> bool:
        door = self._door
        return door is not None and door.state == DOOR_STATE_CLOSING

    # ------------------------------------------------------------------
    # Commands — all use toggle since GDO has no separate open/close
    # ------------------------------------------------------------------

    async def _toggle(self) -> None:
        """Send toggle command via MQTT."""
        door = self._door
        position = door.position if door else None
        try:
            await self.coordinator.api.toggle_door(self._device_id, position)
        except OrbitApiError as err:
            raise HomeAssistantError(f"Failed to toggle door: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the garage door (sends toggle)."""
        await self._toggle()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the garage door (sends toggle)."""
        await self._toggle()

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the garage door mid-travel (sends toggle)."""
        await self._toggle()
