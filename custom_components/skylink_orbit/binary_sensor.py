"""Binary sensor entities for Skylink Orbit garage doors.

Provides a simple Open/Closed status sensor for each garage door.
These are grouped under the same device as the cover entity.
"""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DoorDevice
from .const import DOMAIN, DOOR_STATE_CLOSED, DOOR_STATE_OPEN, DOOR_STATE_OPENING, DOOR_STATE_CLOSING, DOOR_STATE_STOPPED
from .coordinator import SkyLinkOrbitConfigEntry, SkyLinkOrbitCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkyLinkOrbitConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Skylink Orbit binary sensor entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: SkyLinkOrbitCoordinator = data.coordinator

    entities = [
        SkyLinkOrbitDoorSensor(coordinator, device_id, entry)
        for device_id in coordinator.data
    ]

    async_add_entities(entities, update_before_add=False)


class SkyLinkOrbitDoorSensor(
    CoordinatorEntity[SkyLinkOrbitCoordinator], BinarySensorEntity
):
    """Binary sensor showing whether a Skylink garage door is open or closed.

    Convention: is_on = True means the door is OPEN (not closed).
    """

    _attr_device_class = BinarySensorDeviceClass.GARAGE_DOOR
    _attr_has_entity_name = True
    _attr_name = "Door"

    def __init__(
        self,
        coordinator: SkyLinkOrbitCoordinator,
        device_id: str,
        entry: SkyLinkOrbitConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{DOMAIN}_{device_id}_door_sensor"

    # ------------------------------------------------------------------
    # Device info (groups this sensor under the same device as the cover)
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
    # State
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
    def is_on(self) -> bool | None:
        """Return True if the door is open (any non-closed state).

        BinarySensorDeviceClass.GARAGE_DOOR:
            is_on = True  -> "Open"
            is_on = False -> "Closed"
            is_on = None  -> "Unknown"
        """
        door = self._door
        if door is None:
            return None
        if door.state == DOOR_STATE_CLOSED:
            return False
        if door.state in (DOOR_STATE_OPEN, DOOR_STATE_OPENING, DOOR_STATE_CLOSING, DOOR_STATE_STOPPED):
            return True
        return None  # unknown state
