import logging
from typing import Any, Dict, Optional

from homeassistant import config_entries, core
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .api import ApsApi
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

LOGIN_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
})

def validate_path(path: str) -> None:
    """Validates a GitHub repo path.
    Raises a ValueError if the path is invalid.
    """
    if len(path.split("/")) != 2:
        raise ValueError


async def validate_auth(username: str, password: str, hass: core.HomeAssistant) -> None:
    """Validates a GitHub access token.
    Raises a ValueError if the auth token is invalid.
    """
    session = async_get_clientsession(hass)
    try:
        api = ApsApi(session, username, password)
        await api.login()
    except Exception:
        raise ValueError


class ApsApiClientConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Github Custom config flow."""

    data: Optional[Dict[str, Any]]

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        """Invoked when a user initiates a flow via the user interface."""
        errors: Dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_auth(user_input['username'], user_input['password'], self.hass)
            except ValueError:
                errors["base"] = "auth"
            if not errors:
                # Input is valid, set data.
                self.data = user_input
                # Return the form of the next step.
                # return await self.async_step_repo()
                # User is done adding repos, create the config entry.
                return self.async_create_entry(title="APS API client", data=self.data)

        return self.async_show_form(
            step_id="user", data_schema=LOGIN_SCHEMA, errors=errors
        )
