"""Diagnostic decision only; no irrigation services."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from . import DOMAIN

async def async_setup_platform(hass,config,async_add_entities,discovery_info=None):
    data=hass.data[DOMAIN]
    async_add_entities([DecisionSensor(data['coordinator'],data['options'])])

class DecisionSensor(CoordinatorEntity,SensorEntity):
    _attr_name='Lawn Forecast Decision'
    _attr_unique_id='lawn_forecast_guard_decision'
    _attr_icon='mdi:weather-rainy'
    @property
    def native_value(self):
        return (self.coordinator.data or {}).get('decision','unknown')
    @property
    def extra_state_attributes(self):
        data=dict(self.coordinator.data or {})
        data.update({'lookahead_hours':self.options['lookahead_hours'],
                     'rain_threshold_mm':self.options['rain_threshold_mm'],
                     'max_age_seconds':self.options['max_age_minutes']*60})
        return data
    def __init__(self,coordinator,options):
        super().__init__(coordinator);self.options=options
