"""Base entity class for Govee integration.

Provides common functionality for all Govee entities:
- Device info
- Coordinator integration
- State updates
- Transport diagnostics (Cloud API / MQTT / BLE)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_EXPOSE_TRANSPORT_ENTITIES, DOMAIN

if TYPE_CHECKING:
    from .coordinator import GoveeCoordinator
    from .models import GoveeDevice, GoveeDeviceState


class GoveeEntity(CoordinatorEntity["GoveeCoordinator"]):
    """Base class for Govee entities.

    Provides:
    - Automatic coordinator integration
    - Device info with rich metadata
    - Availability tracking
    - has_entity_name = True for Gold tier compliance
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device: GoveeDevice,
    ) -> None:
        """Initialize the entity.

        Args:
            coordinator: Govee data coordinator.
            device: Device this entity represents.
        """
        super().__init__(coordinator)
        self._device = device
        self._device_id = device.device_id

        # Set unique_id based on device
        self._attr_unique_id = device.device_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for device registry."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self._device.device_id)},
            name=self._device.name,
            manufacturer="Govee",
            model=self._device.sku,
            # Suggested area from device name (e.g., "Living Room Lamp" -> "Living Room")
            suggested_area=self._infer_area_from_name(self._device.name),
        )
        # Gateway-bridged devices (e.g. H5310 via H5044) link to their hub so HA
        # shows the relationship. The hub is registered first (#86).
        if self._device.hub_device_id:
            info["via_device"] = (DOMAIN, self._device.hub_device_id)
        return info

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        Checks coordinator health first (via super().available which
        verifies last_update_success), then device-specific status.
        Group devices are always considered available since we can't
        query their state but can still control them.
        """
        if self._device.is_group:
            return True

        if not super().available:
            return False

        state = self.coordinator.get_state(self._device_id)
        return state is not None and state.online

    @property
    def device_state(self) -> GoveeDeviceState | None:
        """Get current device state from coordinator."""
        return self.coordinator.get_state(self._device_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return transport protocol diagnostics for this device.

        Off by default to keep the state machine lean for installs with many
        entities. The same data is available via dedicated diagnostic
        binary_sensor entities. Set
        ``CONF_EXPOSE_TRANSPORT_ENTITIES`` in entry options to True to opt in.
        """
        config_entry = self.coordinator.config_entry
        if config_entry is None or not config_entry.options.get(
            CONF_EXPOSE_TRANSPORT_ENTITIES, False
        ):
            return {}
        return {
            "transport_cloud_api": True,
            "transport_mqtt": self.coordinator.mqtt_connected,
            "transport_ble": self.coordinator.is_ble_available(self._device_id),
        }

    @staticmethod
    def _infer_area_from_name(name: str) -> str | None:
        """Infer area from device name.

        Extracts common room names from device names like:
        - "Living Room Lamp" -> "Living Room"
        - "Bedroom LED Strip" -> "Bedroom"
        - "Kitchen Lights" -> "Kitchen"

        Returns None if no area can be inferred.
        """
        # Common area keywords sorted by length descending (longest match first)
        # so "Master Bedroom Light" matches "Master Bedroom" before "Bedroom"
        areas = [
            "Master Bedroom",
            "Living Room",
            "Dining Room",
            "Front Yard",
            "Guest Room",
            "Media Room",
            "Game Room",
            "Kids Room",
            "Bathroom",
            "Backyard",
            "Basement",
            "Bedroom",
            "Kitchen",
            "Hallway",
            "Nursery",
            "Garage",
            "Office",
            "Patio",
            "Attic",
        ]

        name_lower = name.lower()
        for area in areas:
            if area.lower() in name_lower:
                return area

        return None
