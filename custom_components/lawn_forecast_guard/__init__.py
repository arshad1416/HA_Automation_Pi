"""YAML-configured read-only forecast integration. Candidate; not installed."""
from datetime import timedelta, datetime, timezone
import logging
import voluptuous as vol
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.helpers import config_validation as cv, discovery
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .core import Cache, evaluate
DOMAIN='lawn_forecast_guard'
CONFIG_SCHEMA=vol.Schema({DOMAIN:vol.Schema({
    vol.Required('user_agent'):cv.string,
    vol.Optional('lookahead_hours',default=24):vol.All(vol.Coerce(int),vol.Range(min=1,max=24)),
    vol.Optional('rain_threshold_mm',default=2):vol.All(vol.Coerce(float),vol.Range(min=0.01)),
    # 90 minutes is a proposal; requires explicit deployment agreement.
    vol.Optional('max_age_minutes',default=90):vol.All(vol.Coerce(int),vol.Range(min=1,max=180))
})},extra=vol.ALLOW_EXTRA)

async def async_setup(hass:HomeAssistant,config):
    options=config[DOMAIN]
    ua=options['user_agent'].strip()
    if not ua or 'CONTACT_REQUIRED' in ua:
        raise ValueError('A real identifying User-Agent/contact must be configured')
    cache=Cache();session=async_get_clientsession(hass)
    async def update():
        try:
            return await cache.fetch(session,hass.config.latitude,hass.config.longitude,ua,
                lambda:datetime.now(timezone.utc).timestamp(),options['lookahead_hours'],
                options['rain_threshold_mm'],options['max_age_minutes']*60)
        except Exception as err:
            # Do not emit URLs, coordinates, payloads or HTTP exception details.
            raise UpdateFailed('Forecast decision unavailable; fail closed') from err
    coordinator=DataUpdateCoordinator(hass,logging.getLogger(__name__),name=DOMAIN,config_entry=None,
        update_method=update,update_interval=timedelta(minutes=10))
    # Failure must not prevent setup of an unavailable diagnostic sensor.
    await coordinator.async_refresh()
    hass.data[DOMAIN]={'coordinator':coordinator,'options':options}
    async def evaluate_cached(call):
        if not coordinator.last_update_success or cache.body is None:
            return {'decision':'unknown','reason':'no_successful_available_cache'}
        try:
            result=evaluate(cache.body,datetime.now(timezone.utc).timestamp(),cache.validated_at,
                options['lookahead_hours'],options['rain_threshold_mm'],options['max_age_minutes']*60)
            result['max_age_seconds']=options['max_age_minutes']*60
            return result
        except (ValueError,KeyError,TypeError,OverflowError):
            return {'decision':'unknown','reason':'invalid_or_stale_cache'}
    hass.services.async_register(DOMAIN,'evaluate',evaluate_cached,
        schema=vol.Schema({}),supports_response=SupportsResponse.ONLY)
    await discovery.async_load_platform(hass,'sensor',DOMAIN,{},config)
    return True
