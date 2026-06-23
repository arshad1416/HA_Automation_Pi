"""Skylink Orbit Garage Door integration for Home Assistant.

Controls Skylink G2 garage door openers via the Orbit Home cloud API
at iot.skyhm.net (REST for auth/discovery, MQTT for door control).
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import OrbitAuthError, OrbitConnectionError, OrbitHomeAPI
from .const import CONF_ACC_NO, CONF_BASE_URL, CONF_USERNAME, DEFAULT_BASE_URL, DOMAIN
from .coordinator import SkyLinkOrbitCoordinator, SkyLinkOrbitData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Skylink Orbit from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    base_url = entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
    acc_no = entry.data.get(CONF_ACC_NO, "")
    hub_ids_str = entry.data.get("hub_ids", "")
    hub_ids = [h.strip() for h in hub_ids_str.split(",") if h.strip()]

    api = OrbitHomeAPI(username, password, base_url)

    if acc_no:
        api.set_acc_no(acc_no)
    if hub_ids:
        api.set_hub_ids(hub_ids)

    # Authenticate up front so we fail early on bad credentials
    try:
        await api.authenticate()
    except OrbitAuthError as err:
        await api.close()
        raise ConfigEntryAuthFailed("Invalid credentials") from err
    except OrbitConnectionError as err:
        await api.close()
        raise ConfigEntryNotReady(
            f"Cannot reach Skylink cloud service: {err}"
        ) from err

    # Create the coordinator and do the first data fetch
    coordinator = SkyLinkOrbitCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    # Store runtime data for platform setup and unload
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = SkyLinkOrbitData(api, coordinator)

    # Forward to the cover platform to create entities
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Skylink Orbit config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data: SkyLinkOrbitData = hass.data[DOMAIN].pop(entry.entry_id)
        # close() stops the MQTT loop and closes the HTTP session
        await data.api.close()

    return unload_ok
