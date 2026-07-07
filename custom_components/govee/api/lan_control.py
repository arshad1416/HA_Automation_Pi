"""Native LAN control payload builders.

Maps domain command objects to Govee's LAN (UDP) command payloads
(``turn`` / ``brightness``), mirroring :mod:`mqtt_control` but encoding the
LAN protocol's own conventions. Pure functions — no I/O — so they are
trivially unit-testable and free of socket/asyncio dependencies (Clean
Architecture: domain-adjacent).

Scope is deliberately narrow — only **power** and **brightness** are routed
over LAN. The LAN ``devStatus`` reply exposes exactly four readable fields
(``onOff``, ``brightness`` 0-100, ``color``, ``colorTemInKelvin``), but a
colour write cannot be reliably verified-by-read inside the confirm window
(a device that ignores a ``colorwc`` write still returns a reply), so colour
and colour temperature keep using the REST control path. The H5080/H5083
power-quirk SKUs that :mod:`mqtt_control` special-cases (17/16 power encoding)
also fall back to REST so their quirk is honoured.

Two protocol differences from MQTT are encoded here:

* LAN power uses the key ``value`` with ``1``/``0`` (not MQTT's ``val`` with
  the 17/16 quirk).
* LAN brightness is always on a 0-100 scale, so device-native brightness is
  scaled into that range before being sent.

Reference: docs/govee-protocol-reference.md and the Sprint-6 LAN design.
"""

from __future__ import annotations

from typing import Any

from ..models.commands import (
    BrightnessCommand,
    DeviceCommand,
    PowerCommand,
)
from .mqtt_control import POWER_QUIRK_SKUS

# Govee LAN brightness is always reported and accepted on a 0-100 scale.
LAN_BRIGHTNESS_MIN = 0
LAN_BRIGHTNESS_MAX = 100


def _clamp(value: int, low: int, high: int) -> int:
    """Clamp ``value`` to the inclusive ``[low, high]`` range."""
    return max(low, min(high, value))


def device_brightness_to_lan(native: int, brightness_range: tuple[int, int]) -> int:
    """Scale a device-native brightness down to the LAN 0-100 scale.

    Identity (clamped to 0-100) when the device's brightness range tops out at
    100, since the LAN scale already matches the device scale. Otherwise the
    value is rescaled proportionally across ``brightness_range``.

    Args:
        native: Brightness on the device-native scale (within
            ``brightness_range``).
        brightness_range: The device's ``(min, max)`` brightness bounds.

    Returns:
        Brightness on the LAN 0-100 scale.
    """
    minimum, maximum = brightness_range
    if maximum == LAN_BRIGHTNESS_MAX:
        return _clamp(native, LAN_BRIGHTNESS_MIN, LAN_BRIGHTNESS_MAX)
    span = maximum - minimum
    if span <= 0:
        return LAN_BRIGHTNESS_MIN
    ratio = (native - minimum) / span
    scaled = round(ratio * LAN_BRIGHTNESS_MAX)
    return _clamp(scaled, LAN_BRIGHTNESS_MIN, LAN_BRIGHTNESS_MAX)


def lan_brightness_to_device(v_0_100: int, brightness_range: tuple[int, int]) -> int:
    """Scale a LAN 0-100 brightness up to the device-native scale.

    Inverse of :func:`device_brightness_to_lan`: identity (clamped to 0-100)
    when the device range tops out at 100, otherwise rescaled across
    ``brightness_range``. Round-trips through :func:`device_brightness_to_lan`
    are stable from the LAN side (the coarser 0-100 domain).

    Args:
        v_0_100: Brightness on the LAN 0-100 scale.
        brightness_range: The device's ``(min, max)`` brightness bounds.

    Returns:
        Brightness on the device-native scale.
    """
    minimum, maximum = brightness_range
    if maximum == LAN_BRIGHTNESS_MAX:
        return _clamp(v_0_100, LAN_BRIGHTNESS_MIN, LAN_BRIGHTNESS_MAX)
    span = maximum - minimum
    if span <= 0:
        return minimum
    ratio = _clamp(v_0_100, LAN_BRIGHTNESS_MIN, LAN_BRIGHTNESS_MAX) / LAN_BRIGHTNESS_MAX
    scaled = round(minimum + ratio * span)
    return _clamp(scaled, minimum, maximum)


def command_to_lan(
    command: DeviceCommand, sku: str, brightness_range: tuple[int, int]
) -> tuple[str, dict[str, Any]] | None:
    """Map a command to ``(cmd, data)`` for native LAN control.

    Only power and brightness are routed over LAN. Returns ``None`` for every
    other command (colour, colour temperature, scenes, segments, music, DIY,
    work modes, toggles), signalling the caller to fall back to the REST
    control path. ``None`` is also returned for the H5080/H5083 power-quirk
    SKUs so their 17/16 power encoding (honoured only by the REST/MQTT path)
    is preserved.

    Args:
        command: The domain command to translate.
        sku: The device SKU (model), used to detect power-quirk SKUs.
        brightness_range: The device's ``(min, max)`` brightness bounds, used
            to scale brightness into the LAN 0-100 range.

    Returns:
        A ``(cmd, data)`` tuple for the LAN protocol, or ``None`` if the
        command has no safe LAN representation.
    """
    if isinstance(command, PowerCommand):
        if sku in POWER_QUIRK_SKUS:
            return None
        return ("turn", {"value": 1 if command.power_on else 0})
    if isinstance(command, BrightnessCommand):
        lan_value = device_brightness_to_lan(command.brightness, brightness_range)
        return ("brightness", {"value": lan_value})
    return None
