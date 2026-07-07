"""Native MQTT control payload builders.

Maps domain command objects to Govee's native MQTT command payloads
(``turn`` / ``brightness`` / ``colorwc``), encoding documented device
quirks. Pure functions — no I/O — so they are trivially unit-testable and
free of aiohttp/mqtt dependencies (Clean Architecture: domain-adjacent).

Reference: docs/govee-protocol-reference.md §3.5-3.8 and
docs/_research/2026-06-04_mqtt-push-control-latency.md.
"""

from __future__ import annotations

from typing import Any

from ..models.commands import (
    BrightnessCommand,
    ColorCommand,
    DeviceCommand,
    PowerCommand,
)

# SKUs whose power values are 17 (on) / 16 (off) instead of 1 / 0.
# Source: docs/govee-protocol-reference.md:922-928.
POWER_QUIRK_SKUS = frozenset({"H5080", "H5083"})


def build_turn_data(power_on: bool, sku: str) -> dict[str, Any]:
    """Build the ``data`` payload for a native ``turn`` command.

    H5080/H5083 use 17 (on) / 16 (off); all other SKUs use 1 / 0.
    """
    if sku in POWER_QUIRK_SKUS:
        return {"val": 17 if power_on else 16}
    return {"val": 1 if power_on else 0}


def build_brightness_data(brightness_1_100: int) -> dict[str, Any]:
    """Build the ``data`` payload for a native ``brightness`` command.

    Args:
        brightness_1_100: Brightness on Govee's 1-100 scale (the caller is
            responsible for mapping HA's 0-255 range before calling).
    """
    return {"val": brightness_1_100}


def build_color_data(r: int, g: int, b: int) -> dict[str, Any]:
    """Build the ``data`` payload for a native ``colorwc`` command (preferred)."""
    return {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0}


def build_color_legacy_data(r: int, g: int, b: int) -> dict[str, Any]:
    """Build the ``data`` payload for the legacy ``color`` command.

    Used as a fallback for older devices that do not respond to ``colorwc``.
    Sent with ``cmdVersion=1``.
    """
    return {"r": r, "g": g, "b": b}


def command_to_mqtt(
    command: DeviceCommand, sku: str
) -> tuple[str, dict[str, Any], int] | None:
    """Map a command to ``(cmd, data, cmd_version)`` for native MQTT control.

    Returns ``None`` for commands that have no native MQTT representation
    (color temperature, scenes, segments, etc.), signalling the caller to
    fall back to the REST control path.
    """
    if isinstance(command, PowerCommand):
        return ("turn", build_turn_data(command.power_on, sku), 0)
    if isinstance(command, BrightnessCommand):
        return ("brightness", build_brightness_data(command.brightness), 0)
    if isinstance(command, ColorCommand):
        color = command.color
        return ("colorwc", build_color_data(color.r, color.g, color.b), 0)
    return None
