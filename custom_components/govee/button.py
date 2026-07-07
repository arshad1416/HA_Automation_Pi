"""Button platform for Govee integration.

Provides button entities for:
- Refresh scenes (per device)
- Clear Water Alert (dehumidifiers with a waterFullEvent capability)
- Identify device (flash lights if supported)
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SUFFIX_REFRESH_SCENES
from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .models import GoveeDevice

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Govee buttons from a config entry."""
    coordinator: GoveeCoordinator = entry.runtime_data

    entities: list[ButtonEntity] = []

    for device in coordinator.devices.values():
        # Add refresh scenes button for devices with scenes
        if device.supports_scenes:
            entities.append(GoveeRefreshScenesButton(coordinator, device))
        # Pairs with the Water Tank Full binary sensor — Govee never pushes a
        # cleared event, so the user acknowledges the alert manually (#118).
        if not device.is_group and device.supports_water_full_event:
            entities.append(GoveeClearWaterFullButton(coordinator, device))

    async_add_entities(entities)
    _LOGGER.debug("Set up %d Govee button entities", len(entities))


class GoveeRefreshScenesButton(GoveeEntity, ButtonEntity):
    """Button to refresh scenes for a device.

    Useful when new scenes are created in the Govee app.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "refresh_scenes"
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device: GoveeDevice,
    ) -> None:
        """Initialize the refresh scenes button."""
        super().__init__(coordinator, device)

        self._attr_unique_id = f"{device.device_id}{SUFFIX_REFRESH_SCENES}"
        self._attr_name = "Refresh Scenes"

    async def async_press(self) -> None:
        """Handle the button press - refresh scenes."""
        _LOGGER.debug("Refreshing scenes for %s", self._device.name)

        # Force refresh scenes from API
        await self.coordinator.async_get_scenes(
            self._device_id,
            refresh=True,
        )

        _LOGGER.info("Scenes refreshed for %s", self._device.name)


class GoveeClearWaterFullButton(GoveeEntity, ButtonEntity):
    """Button to clear the latched Water Tank Full alert (issue #118).

    The ``waterFullEvent`` push has no cleared counterpart (confirmed live
    in #118 across two pull→re-insert cycles), so the user acknowledges the
    alert after emptying/re-inserting the tank. A later value=1 event
    re-latches the sensor. No entity_category — it is a user-facing control
    paired with the alert sensor, unlike the CONFIG refresh button.
    """

    _attr_translation_key = "clear_water_full"
    _attr_icon = "mdi:water-check"

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device: GoveeDevice,
    ) -> None:
        """Initialize the clear-water-alert button."""
        super().__init__(coordinator, device)

        self._attr_unique_id = f"{device.device_id}_clear_water_full"

    @property
    def available(self) -> bool:
        """Available whenever the coordinator is — not gated on device online.

        The button clears a locally latched alert; that must not require the
        device to be reachable (same rationale as the leak sensor's
        coordinator-level availability).
        """
        return self.coordinator.last_update_success

    async def async_press(self) -> None:
        """Handle the button press — clear the latched alert."""
        _LOGGER.debug("Clearing water-tank-full alert for %s", self._device.name)
        self.coordinator.clear_water_full(self._device_id)
