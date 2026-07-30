import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
import logging
import requests
import asyncio

from .const import (
    DOMAIN, 
    CONF_EMAIL, 
    CONF_PASSWORD, 
    CONF_GEMINI_API_KEY, 
    CONF_REGION, 
    CONF_LANGUAGE,
    CONF_MAPBOX_TOKEN,
    CONF_STADIA_TOKEN,
    REGION_CONFIG,
)

_LOGGER = logging.getLogger(__name__)

CONF_GEMINI_MODEL = "gemini_model"
CONF_AUTH_MODE = "auth_mode"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"

REGIONS = {"VN": "Vietnam (VN)", "US": "United States (US)", "EU": "Europe (EU)"}
LANGUAGES = {"vi": "Vietnamese (VI)", "en": "English (EN)"}

def safe_int(val, default):
    try: return int(float(val))
    except (ValueError, TypeError): return default

# =====================================================================
# THUẬT TOÁN TỰ ĐỘNG QUÉT DANH SÁCH MODEL MỚI NHẤT TỪ GOOGLE GEMINI
# =====================================================================
def fetch_gemini_models_sync(api_key):
    # Fallback list if network fails or user does not enter Key
    default_models = {
        "gemini-2.5-flash": "Gemini 2.5 Flash (Recommended/Fast/Free)",
        "gemini-2.5-pro": "Gemini 2.5 Pro (Premium)",
        "gemini-2.0-flash": "Gemini 2.0 Flash (Nhanh/Free)",
        "gemini-1.5-flash": "Gemini 1.5 Flash",
    }
    
    if not api_key or str(api_key).strip() == "":
        return default_models
        
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        res = requests.get(url, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            models = {}
            
            for m in data.get("models", []):
                name = m.get("name", "").replace("models/", "")
                display = m.get("displayName", name)
                methods = m.get("supportedGenerationMethods", [])
                
                # Only get text generation models (Skip embedding/audio/legacy models)
                if "generateContent" in methods and "gemini" in name.lower() and "vision" not in name.lower():
                    # Apply smart classification tag
                    if "flash" in name.lower():
                        display = f"{display} (Nhanh/Free)"
                    elif "pro" in name.lower():
                        display = f"{display} (Premium)"
                    
                    models[name] = display
            
            if models:
                # Sort algorithm: Prioritize 2.5 series first -> Then Flash series -> Others
                sorted_models = dict(sorted(models.items(), key=lambda item: (
                    not ("2.5" in item[0]), 
                    not ("flash" in item[0]), 
                    item[0]
                )))
                return sorted_models
                
    except Exception as e:
        _LOGGER.error(f"VinFast: Error fetching dynamic Gemini model list: {e}")
        
    return default_models


def start_device_flow_sync(region):
    """Start device code flow - runs in executor."""
    cfg = REGION_CONFIG.get(region, REGION_CONFIG["US"])
    auth0_domain = cfg["AUTH0_DOMAIN"]
    client_id = cfg["AUTH0_CLIENT_ID"]
    
    url = f"https://{auth0_domain}/oauth/device/code"
    try:
        res = requests.post(url, json={
            "client_id": client_id,
            "scope": "openid profile email offline_access"
        }, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return {
                "device_code": data.get("device_code"),
                "user_code": data.get("user_code"),
                "verification_uri": data.get("verification_uri"),
                "verification_uri_complete": data.get("verification_uri_complete"),
                "interval": int(data.get("interval", 5)),
                "expires_in": int(data.get("expires_in", 900))
            }
        _LOGGER.error(f"VinFast device flow start failed: HTTP {res.status_code} - {res.text[:200]}")
    except Exception as e:
        _LOGGER.error(f"VinFast device flow start failed: {e}")
    return None


def poll_device_token_sync(region, device_code):
    """Poll for device code token - runs in executor."""
    cfg = REGION_CONFIG.get(region, REGION_CONFIG["US"])
    auth0_domain = cfg["AUTH0_DOMAIN"]
    client_id = cfg["AUTH0_CLIENT_ID"]
    
    url = f"https://{auth0_domain}/oauth/token"
    try:
        res = requests.post(url, json={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": client_id
        }, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return {
                "access_token": data.get("access_token"),
                "refresh_token": data.get("refresh_token"),
                "expires_in": int(data.get("expires_in", 3600)),
            }
        try:
            error_data = res.json()
            error_code = error_data.get("error", "unknown")
            return {"error": error_code}
        except Exception:
            _LOGGER.error(f"VinFast device flow poll failed: HTTP {res.status_code} - {res.text[:200]}")
    except Exception as e:
        _LOGGER.error(f"VinFast device flow poll failed: {e}")
    return None


class VinFastConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._setup_data = {}
        self._device_flow_data = None
        self._poll_count = 0
        self._device_token_result = None
        self._poll_task = None
        self._polling_active = False

    async def async_step_user(self, user_input=None):
        # BƯỚC 1: CHỌN AUTH MODE
        if user_input is not None:
            auth_mode = user_input.get(CONF_AUTH_MODE, "password")
            self._setup_data[CONF_AUTH_MODE] = auth_mode
            
            # Region is needed for both flows
            self._setup_data[CONF_REGION] = user_input.get(CONF_REGION, "US")
            self._setup_data[CONF_LANGUAGE] = user_input.get(CONF_LANGUAGE, "en")
            
            if auth_mode == "device_code":
                return await self.async_step_device_code()
            else:
                return await self.async_step_credentials()

        data_schema = vol.Schema({
            vol.Required(CONF_AUTH_MODE, default="password"): vol.In({
                "password": "Password Grant (Recommended)",
                "device_code": "Device Code Flow (Alternative)"
            }),
            vol.Required(CONF_REGION, default="US"): vol.In(REGIONS),
            vol.Required(CONF_LANGUAGE, default="en"): vol.In(LANGUAGES),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_credentials(self, user_input=None):
        """Legacy password grant flow."""
        if user_input is not None:
            self._setup_data.update(user_input)
            return await self.async_step_model()

        data_schema = vol.Schema({
            vol.Required(CONF_EMAIL): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_GEMINI_API_KEY, default=""): str,
            vol.Optional(CONF_MAPBOX_TOKEN, default=""): str,
            vol.Optional(CONF_STADIA_TOKEN, default=""): str,
        })
        return self.async_show_form(step_id="credentials", data_schema=data_schema)

    async def _auto_poll_loop(self):
        """Background polling loop: polls every 5s until success, error, or expiry."""
        import time as _time
        device_code = self._device_flow_data.get("device_code")
        region = self._setup_data.get(CONF_REGION, "US")
        interval = self._device_flow_data.get("interval", 5)
        expires_in = self._device_flow_data.get("expires_in", 900)
        started_at = _time.time()

        try:
            while self._polling_active:
                # Check expiry
                if _time.time() - started_at >= expires_in:
                    self._device_token_result = {"error": "expired_token"}
                    return

                # Wait before polling
                await asyncio.sleep(interval)

                if not self._polling_active:
                    return

                result = await self.hass.async_add_executor_job(
                    poll_device_token_sync, region, device_code
                )
                self._poll_count += 1

                if not result:
                    # Network error, retry
                    continue

                if result.get("access_token"):
                    # Success!
                    self._device_token_result = result
                    return

                error = result.get("error", "")
                if error == "authorization_pending":
                    # Keep polling
                    continue
                elif error == "slow_down":
                    interval = min(interval + 5, 30)
                    continue
                elif error in ("expired_token", "access_denied", "invalid_grant"):
                    self._device_token_result = result
                    return
                else:
                    # Unknown error, keep trying
                    _LOGGER.warning(f"VinFast device poll: unexpected error '{error}'")
                    continue
        except asyncio.CancelledError:
            return
        except Exception as e:
            _LOGGER.error(f"VinFast auto-poll loop error: {e}")
            self._device_token_result = {"error": "poll_error"}

    async def async_step_device_code(self, user_input=None):
        """Device code flow - show URL/code and auto-poll for token."""
        import time as _time
        errors = {}

        if user_input is not None:
            # User clicked Continue — check if background poll already got a token
            if self._device_token_result and self._device_token_result.get("access_token"):
                # Background poll succeeded
                self._polling_active = False
                result = self._device_token_result
                self._device_token_result = None
                self._setup_data[CONF_ACCESS_TOKEN] = result["access_token"]
                self._setup_data[CONF_REFRESH_TOKEN] = result.get("refresh_token", "")
                self._setup_data[CONF_EMAIL] = f"device_flow_{int(_time.time())}"
                _LOGGER.info(f"VinFast: Device code authorized! (poll #{self._poll_count})")
                return await self.async_step_model()

            # Cancel any running background poll
            if self._poll_task and not self._poll_task.done():
                self._poll_task.cancel()
                try:
                    await self._poll_task
                except asyncio.CancelledError:
                    pass
                self._poll_task = None
            self._polling_active = False

            # Do one immediate poll right now
            if self._device_flow_data:
                device_code = self._device_flow_data.get("device_code")
                region = self._setup_data.get(CONF_REGION, "US")
                result = await self.hass.async_add_executor_job(
                    poll_device_token_sync, region, device_code
                )
                self._poll_count += 1

                if result and result.get("access_token"):
                    # Success!
                    self._device_token_result = None
                    self._setup_data[CONF_ACCESS_TOKEN] = result["access_token"]
                    self._setup_data[CONF_REFRESH_TOKEN] = result.get("refresh_token", "")
                    self._setup_data[CONF_EMAIL] = f"device_flow_{int(_time.time())}"
                    _LOGGER.info(f"VinFast: Device code authorized on click! (poll #{self._poll_count})")
                    return await self.async_step_model()
                elif result and result.get("error") == "expired_token":
                    # Expired — restart flow
                    self._device_flow_data = None
                    self._device_token_result = None
                    return await self.async_step_device_code()
                elif result and result.get("error") == "authorization_pending":
                    errors["base"] = "authorization_pending"
                elif result and result.get("error") == "slow_down":
                    errors["base"] = "slow_down"
                else:
                    errors["base"] = "unknown_error"

            # Start background auto-polling loop
            self._polling_active = True
            self._device_token_result = None
            self._poll_task = asyncio.create_task(self._auto_poll_loop())

        # Start new device flow if not already started
        if not self._device_flow_data:
            region = self._setup_data.get(CONF_REGION, "US")
            self._device_flow_data = await self.hass.async_add_executor_job(
                start_device_flow_sync, region
            )
            self._poll_count = 0
            self._device_token_result = None

        if not self._device_flow_data:
            return self.async_abort(reason="device_flow_failed")

        user_code = self._device_flow_data.get("user_code", "XXXX-XXXX")
        verification_uri = self._device_flow_data.get("verification_uri", "https://vinfast-ca.us.auth0.com/activate")
        verification_uri_complete = self._device_flow_data.get("verification_uri_complete", "")

        # Build description
        if errors.get("base") == "authorization_pending":
            description = (
                f"\u23f3 Waiting for authorization... (poll #{self._poll_count})\n\n"
                f"Open {verification_uri} in your browser and enter code: **{user_code}**\n\n"
                f"Auto-polling every {self._device_flow_data.get('interval', 5)}s. "
                f"Click Continue to check now."
            )
        elif errors.get("base") == "slow_down":
            description = (
                f"\u23f3 Please wait...\n\n"
                f"Open {verification_uri} in your browser and enter code: **{user_code}**\n\n"
                f"Click Continue to check."
            )
        elif errors.get("base") == "expired_token":
            self._device_flow_data = None
            return await self.async_step_device_code()
        else:
            if verification_uri_complete:
                description = (
                    f"Open this link in your browser:\n\n"
                    f"**{verification_uri_complete}**\n\n"
                    f"Or go to {verification_uri} and enter code: **{user_code}**\n\n"
                    f"Then click Continue below. Auto-polling will start after first click."
                )
            else:
                description = (
                    f"Open {verification_uri} in your browser and enter code: **{user_code}**\n\n"
                    f"Then click Continue below. Auto-polling will start after first click."
                )

        data_schema = vol.Schema({})
        return self.async_show_form(
            step_id="device_code",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"instructions": description}
        )

    async def async_step_model(self, user_input=None):
        # BƯỚC 2: TỰ ĐỘNG LOAD MODEL VÀ CHỐT LƯU
        if user_input is not None:
            self._setup_data.update(user_input)
            email = self._setup_data.get(CONF_EMAIL, "vinfast_device")
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=email, data=self._setup_data)

        api_key = self._setup_data.get(CONF_GEMINI_API_KEY, "")
        
        # Run API fetch in background to avoid blocking Home Assistant UI
        models = await self.hass.async_add_executor_job(fetch_gemini_models_sync, api_key)
        
        data_schema = vol.Schema({
            vol.Required(CONF_GEMINI_MODEL, default=list(models.keys())[0]): vol.In(models),
        })
        return self.async_show_form(step_id="model", data_schema=data_schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return VinFastOptionsFlowHandler(config_entry)

class VinFastOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry):
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        data = self._config_entry.data
        
        current_region = opts.get(CONF_REGION, data.get(CONF_REGION, "VN"))
        current_lang = opts.get(CONF_LANGUAGE, data.get(CONF_LANGUAGE, "vi"))
        current_gemini_key = opts.get(CONF_GEMINI_API_KEY, data.get(CONF_GEMINI_API_KEY, ""))
        current_gemini_model = opts.get(CONF_GEMINI_MODEL, data.get(CONF_GEMINI_MODEL, "gemini-2.5-flash"))
        current_mapbox = opts.get(CONF_MAPBOX_TOKEN, data.get(CONF_MAPBOX_TOKEN, ""))
        current_stadia = opts.get(CONF_STADIA_TOKEN, data.get(CONF_STADIA_TOKEN, ""))

        # Refresh model list each time user clicks Reconfigure
        available_models = await self.hass.async_add_executor_job(fetch_gemini_models_sync, current_gemini_key)
        if current_gemini_model not in available_models:
            available_models[current_gemini_model] = current_gemini_model

        # Add Mapbox and Stadia to the Reconfigure form
        options_schema = vol.Schema({
            vol.Required(CONF_REGION, default=current_region): vol.In(REGIONS),
            vol.Required(CONF_LANGUAGE, default=current_lang): vol.In(LANGUAGES),
            vol.Optional(CONF_GEMINI_API_KEY, default=current_gemini_key): str,
            vol.Required(CONF_GEMINI_MODEL, default=current_gemini_model): vol.In(available_models),
            vol.Optional(CONF_MAPBOX_TOKEN, default=current_mapbox): str,
            vol.Optional(CONF_STADIA_TOKEN, default=current_stadia): str,
            vol.Required("cost_per_kwh", default=safe_int(opts.get("cost_per_kwh"), 4000)): vol.Coerce(int),
            vol.Required("gas_price", default=safe_int(opts.get("gas_price"), 20000)): vol.Coerce(int),
        })
        
        return self.async_show_form(step_id="init", data_schema=options_schema)
