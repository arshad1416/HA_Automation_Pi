"""Config flow for Skylink Orbit Garage Door integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import callback

from .api import OrbitApiError, OrbitAuthError, OrbitConnectionError, OrbitHomeAPI
from .const import CONF_ACC_NO, CONF_BASE_URL, CONF_USERNAME, DEFAULT_BASE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Step 1: credentials + hub IDs
USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required("hub_ids"): str,
        vol.Optional(CONF_ACC_NO): str,
        vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
    }
)

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): str,
    }
)


class SkyLinkOrbitConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Skylink Orbit."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_username: str | None = None
        self._reauth_base_url: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return SkyLinkOrbitOptionsFlow(config_entry)

    # ------------------------------------------------------------------
    # Initial setup step
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            base_url = user_input.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            acc_no = user_input.get(CONF_ACC_NO, "")

            raw_hubs = user_input.get("hub_ids", "")
            hub_ids = [h.strip() for h in raw_hubs.split(",") if h.strip()]

            if not hub_ids:
                errors["hub_ids"] = "no_hub_ids"
            else:
                await self.async_set_unique_id(username.lower())
                self._abort_if_unique_id_configured()

                api = OrbitHomeAPI(username, password, base_url)
                if acc_no:
                    api.set_acc_no(acc_no)
                api.set_hub_ids(hub_ids)

                try:
                    login_data = await api.authenticate()
                    if not acc_no:
                        acc_no = login_data.get("acc_no", "")
                    _LOGGER.info(
                        "Authenticated OK. acc_no=%s, hub_ids=%s",
                        acc_no, hub_ids,
                    )
                except OrbitAuthError as err:
                    _LOGGER.error("Authentication failed: %s", err)
                    errors["base"] = "invalid_auth"
                except OrbitConnectionError as err:
                    _LOGGER.error("Connection failed: %s", err)
                    errors["base"] = "cannot_connect"
                except OrbitApiError as err:
                    _LOGGER.error("API error: %s", err)
                    errors["base"] = "unknown"
                finally:
                    await api.close()

            if not errors:
                return self.async_create_entry(
                    title=f"Skylink ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_BASE_URL: base_url,
                        CONF_ACC_NO: acc_no,
                        "hub_ids": ",".join(hub_ids),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Reauth flow
    # ------------------------------------------------------------------

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        self._reauth_username = entry_data[CONF_USERNAME]
        self._reauth_base_url = entry_data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            api = OrbitHomeAPI(
                self._reauth_username,  # type: ignore[arg-type]
                password,
                self._reauth_base_url,  # type: ignore[arg-type]
            )
            try:
                await api.authenticate()
            except OrbitAuthError:
                errors["base"] = "invalid_auth"
            except OrbitConnectionError:
                errors["base"] = "cannot_connect"
            except OrbitApiError:
                errors["base"] = "unknown"
            finally:
                await api.close()

            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"username": self._reauth_username or ""},
        )


# ======================================================================
# Options flow - lets user add/remove hub IDs after setup
# ======================================================================

class SkyLinkOrbitOptionsFlow(OptionsFlow):
    """Handle options for Skylink Orbit (edit hub IDs)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show form with current hub IDs for editing."""
        if user_input is not None:
            raw_hubs = user_input.get("hub_ids", "")
            hub_ids = [h.strip() for h in raw_hubs.split(",") if h.strip()]

            if not hub_ids:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._build_schema(),
                    errors={"hub_ids": "no_hub_ids"},
                )

            # Update the config entry data with new hub_ids
            new_data = {**self._config_entry.data, "hub_ids": ",".join(hub_ids)}
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )

            # Reload the integration so new devices appear
            await self.hass.config_entries.async_reload(self._config_entry.entry_id)

            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=self._build_schema(),
        )

    def _build_schema(self) -> vol.Schema:
        current_hubs = self._config_entry.data.get("hub_ids", "")
        return vol.Schema(
            {
                vol.Required("hub_ids", default=current_hubs): str,
            }
        )
