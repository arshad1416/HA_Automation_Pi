"""Humidifier platform for Govee integration.

Exposes Govee humidifiers and dehumidifiers (e.g. H7150) as HA humidifier
entities with on/off, target-humidity, and mode selection.

Mode mapping (H7150 dehumidifier reference device):
- ``gearMode`` (workMode=1) — manual speed (Low=1, High=3)
- ``Auto``     (workMode=3) — humidity-target mode (30–80%)
- ``Dryer``    (workMode=8) — fixed-dry mode (modeValue ignored)

The API does not expose a current-humidity reading for H7150, so this
platform reports target humidity only.

Target-humidity writes (issue #118):
- H7150-style devices (Auto modeValue is a real 30-80 setpoint range) receive
  BOTH the ``work_mode`` Auto+setpoint write — which switches the unit into
  Auto, required for the target to take effect, matching the Govee app — and
  the canonical ``range::humidity`` setpoint write, carrying the same clamped
  value. Both are the only write paths govee2mqtt uses for this device family
  too (it has no reverse-engineered raw-protocol path for H7150/H7151/H7152,
  unlike its H7160 humidifier support) — neither is confirmed to actually move
  the physical setpoint on all firmware revisions; some reports (#118) show
  Govee's cloud accepting both writes with HTTP 200 while the unit doesn't
  change. The dual write is a best-effort hedge, not a proven fix.
- H7152-style devices (Auto modeValue pinned, e.g. 80..80) receive only
  ``range::humidity`` — an arbitrary modeValue would be rejected with
  "Parameter value out of range" (issue #114; govee2mqtt #145).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
)
from homeassistant.components.humidifier.const import HumidifierEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import GoveeCoordinator
from .entity import GoveeEntity
from .models import GoveeDevice, PowerCommand, RangeCommand, WorkModeCommand
from .models.device import INSTANCE_HUMIDITY

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# Canonical mode names surfaced to Home Assistant. The set of modes offered
# by a given device is intersected with these at entity-construction time.
MODE_LOW = "low"
MODE_MEDIUM = "medium"
MODE_HIGH = "high"
MODE_AUTO = "auto"
MODE_DRYER = "dryer"

# gearMode sub-option names map onto these canonical HA modes.
_GEAR_MODES = (MODE_LOW, MODE_MEDIUM, MODE_HIGH)

# Map canonical HA mode name -> (govee_mode_name, fallback_mode_value).
# govee_mode_name is matched case-insensitively against the device's
# work_mode and gear options. fallback_mode_value is used when the device's
# capability doesn't specify a value (e.g. Dryer always sends 0).
_MODE_ALIASES: dict[str, tuple[str, int]] = {
    MODE_LOW: ("low", 1),
    MODE_MEDIUM: ("medium", 2),
    MODE_HIGH: ("high", 3),
    MODE_AUTO: ("auto", 0),
    MODE_DRYER: ("dryer", 0),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Govee humidifier entities from a config entry."""
    coordinator: GoveeCoordinator = entry.runtime_data

    entities: list[HumidifierEntity] = []
    for device in coordinator.devices.values():
        if device.is_humidifier and not device.is_group:
            entities.append(GoveeHumidifierEntity(coordinator, device))
            _LOGGER.debug(
                "Created humidifier entity for %s (%s, type=%s)",
                device.name,
                device.sku,
                device.device_type,
            )

    async_add_entities(entities)


class GoveeHumidifierEntity(GoveeEntity, HumidifierEntity, RestoreEntity):
    """Govee humidifier / dehumidifier entity."""

    _attr_translation_key = "govee_humidifier"
    _attr_supported_features = HumidifierEntityFeature.MODES

    def __init__(
        self,
        coordinator: GoveeCoordinator,
        device: GoveeDevice,
    ) -> None:
        """Initialize the humidifier entity."""
        super().__init__(coordinator, device)
        self._attr_name = None  # use device name (has_entity_name = True)

        self._attr_device_class = (
            HumidifierDeviceClass.DEHUMIDIFIER
            if device.is_dehumidifier
            else HumidifierDeviceClass.HUMIDIFIER
        )

        min_h, max_h = device.get_humidity_range()
        self._attr_min_humidity = min_h
        self._attr_max_humidity = max_h

        # H7150 carries the target in the Auto modeValue; H7152 pins Auto to a
        # fixed point and carries the setpoint in a separate range::humidity
        # capability instead. Pick the right read/write path per device (#114).
        self._auto_modevalue_is_setpoint = device.auto_mode_value_is_setpoint()
        self._has_humidity_range = device.supports_humidity_range

        # Last user-set target for Auto-setpoint devices (H7150). Govee's poll
        # never reports the live Auto setpoint, and a None target_humidity
        # hides HA's humidity dial entirely — making the target UNSETTABLE
        # from the UI (issue #118 follow-up). Restored across restarts.
        self._optimistic_target: int | None = None

        # Build per-device maps from the capability so the entity honours
        # whatever the device actually advertises (values may vary by SKU).
        self._mode_to_work_mode: dict[str, int] = {}
        self._mode_to_mode_value: dict[str, int] = {}
        self._work_mode_to_mode: dict[int, str] = {}
        self._gear_mode_values: dict[str, int] = {}

        for opt in device.get_humidifier_work_mode_options():
            name = str(opt.get("name", "")).strip().lower()
            value = opt.get("value")
            if value is None:
                continue
            for ha_mode, (alias, _default) in _MODE_ALIASES.items():
                if name == alias and ha_mode not in _GEAR_MODES:
                    self._mode_to_work_mode[ha_mode] = int(value)
                    self._work_mode_to_mode[int(value)] = ha_mode

        # gearMode carries the Low/High sub-options. We map each into a
        # top-level HA mode so users get one flat dropdown.
        gear_work_mode = self._mode_to_work_mode.get("gearmode")
        # The work_mode option may have been named "gearMode" rather than
        # matching an HA alias — locate it explicitly.
        if gear_work_mode is None:
            for opt in device.get_humidifier_work_mode_options():
                if str(opt.get("name", "")).strip().lower() == "gearmode":
                    gear_work_mode = int(opt["value"])
                    break

        if gear_work_mode is not None:
            for gear in device.get_humidifier_gear_options():
                name = str(gear.get("name", "")).strip().lower()
                value = gear.get("value")
                if value is None:
                    continue
                if name in _GEAR_MODES:
                    self._mode_to_work_mode[name] = gear_work_mode
                    self._mode_to_mode_value[name] = int(value)
                    self._gear_mode_values[name] = int(value)

        # Dryer / Auto use a fixed mode_value (0) unless specified.
        for ha_mode in (MODE_AUTO, MODE_DRYER):
            if ha_mode in self._mode_to_work_mode:
                self._mode_to_mode_value.setdefault(ha_mode, _MODE_ALIASES[ha_mode][1])

        # Final mode list, ordered for a consistent UI.
        ordered = [MODE_LOW, MODE_MEDIUM, MODE_HIGH, MODE_AUTO, MODE_DRYER]
        self._attr_available_modes = [
            m for m in ordered if m in self._mode_to_work_mode
        ]

    async def async_added_to_hass(self) -> None:
        """Restore the last user-set target humidity on startup."""
        await super().async_added_to_hass()
        if not self._auto_modevalue_is_setpoint:
            return
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        restored = last_state.attributes.get("humidity")
        try:
            restored_int = int(restored)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if self._attr_min_humidity <= restored_int <= self._attr_max_humidity:
            self._optimistic_target = restored_int

    # --------------------------------------------------------------------- #
    # State
    # --------------------------------------------------------------------- #

    @property
    def is_on(self) -> bool | None:
        """Return True if the device is powered on."""
        state = self.device_state
        return state.power_state if state else None

    @property
    def mode(self) -> str | None:
        """Return the current operating mode."""
        state = self.device_state
        if state is None or state.work_mode is None:
            return None
        ha_mode = self._work_mode_to_mode.get(state.work_mode)
        if ha_mode is None:
            # gearMode — disambiguate by mode_value.
            for name, gear_val in self._gear_mode_values.items():
                if state.mode_value == gear_val and (
                    self._mode_to_work_mode.get(name) == state.work_mode
                ):
                    return name
        return ha_mode

    @property
    def target_humidity(self) -> int | None:
        """Return the target humidity percentage.

        For H7150-style devices the setpoint lives in the Auto-mode modeValue
        and is only meaningful while in Auto. For H7152-style devices it lives
        in the persistent ``range::humidity`` capability and applies regardless
        of mode (issue #114).
        """
        state = self.device_state
        if state is None:
            return None
        if self._auto_modevalue_is_setpoint:
            auto_work_mode = self._mode_to_work_mode.get(MODE_AUTO)
            if (
                auto_work_mode is not None
                and state.work_mode == auto_work_mode
                and state.mode_value is not None
                and self._attr_min_humidity <= state.mode_value <= self._attr_max_humidity
            ):
                return int(state.mode_value)
            # Govee's /device/state poll returns ``modeValue: 0`` for Auto — it
            # never populates the live Auto setpoint — so an out-of-range value
            # means "not reported" (issue #118; same gap in govee2mqtt #413).
            # Fall back to the last user-set target (optimistic + restored):
            # returning None here hides HA's humidity dial entirely, making the
            # target unsettable from the UI (#118 follow-up). A never-set
            # entity falls back to the range minimum so the dial stays usable —
            # dragging it sends a real setpoint and self-corrects.
            if self._optimistic_target is not None:
                return self._optimistic_target
            return int(self._attr_min_humidity)
        return state.configured_humidity

    # --------------------------------------------------------------------- #
    # Commands
    # --------------------------------------------------------------------- #

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the humidifier on."""
        await self.coordinator.async_control_device(
            self._device_id, PowerCommand(power_on=True)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the humidifier off."""
        await self.coordinator.async_control_device(
            self._device_id, PowerCommand(power_on=False)
        )

    async def async_set_mode(self, mode: str) -> None:
        """Set the operating mode."""
        work_mode = self._mode_to_work_mode.get(mode)
        if work_mode is None:
            raise ValueError(f"Unsupported mode for {self._device.sku}: {mode}")

        if mode == MODE_AUTO:
            # Preserve the current target humidity if one was set; fall back
            # to the last user-set target, then the device's minimum, so the
            # unit has a sensible setpoint to aim at.
            state = self.device_state
            mode_value = (
                state.mode_value
                if state and state.work_mode == work_mode and state.mode_value
                else (self._optimistic_target or self._attr_min_humidity)
            )
        else:
            mode_value = self._mode_to_mode_value.get(mode, 0)

        await self.coordinator.async_control_device(
            self._device_id,
            WorkModeCommand(work_mode=work_mode, mode_value=int(mode_value)),
        )

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the target humidity.

        H7152-style devices (Auto modeValue pinned, e.g. 80..80) set it via the
        dedicated ``range::humidity`` capability only (RangeCommand) — sending
        an arbitrary Auto modeValue would be rejected with "Parameter value out
        of range" (issue #114; govee2mqtt #145).

        H7150-style devices (Auto modeValue is the setpoint) receive BOTH the
        ``work_mode`` Auto+setpoint write — which switches the unit into Auto,
        required for the target to take effect, matching the Govee app — and,
        when the device also advertises ``range::humidity``, the canonical
        range setpoint write. Both writes carry the same clamped value so
        either firmware interpretation converges — a best-effort hedge, not a
        confirmed fix: some H7150 units accept both writes (HTTP 200) without
        the physical setpoint moving (issue #118). The coordinator schedules a
        delayed re-poll after either write so a diagnostics download shows
        what Govee reports back, correlated in time with the command.
        """
        clamped = max(self._attr_min_humidity, min(self._attr_max_humidity, humidity))

        if not self._auto_modevalue_is_setpoint and self._has_humidity_range:
            await self.coordinator.async_control_device(
                self._device_id,
                RangeCommand(range_instance=INSTANCE_HUMIDITY, value=int(clamped)),
            )
            return

        auto_work_mode = self._mode_to_work_mode.get(MODE_AUTO)
        if auto_work_mode is None:
            raise ValueError(
                f"{self._device.sku} does not support target-humidity (Auto) mode"
            )

        mode_ok = await self.coordinator.async_control_device(
            self._device_id,
            WorkModeCommand(work_mode=auto_work_mode, mode_value=int(clamped)),
        )
        range_ok = False
        if self._has_humidity_range:
            range_ok = await self.coordinator.async_control_device(
                self._device_id,
                RangeCommand(range_instance=INSTANCE_HUMIDITY, value=int(clamped)),
            )
        _LOGGER.debug(
            "Set target humidity %s%% on %s (%s): work_mode write %s, range write %s",
            int(clamped),
            self._device.name,
            self._device.sku,
            "ok" if mode_ok else "failed",
            ("ok" if range_ok else "failed") if self._has_humidity_range else "skipped",
        )
        if mode_ok or range_ok:
            # Remember the setpoint — the poll never reports it back (#118).
            self._optimistic_target = int(clamped)
            self.async_write_ha_state()
