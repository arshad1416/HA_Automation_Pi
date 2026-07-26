import logging
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import ApiAuthError, ApsApi


_LOGGER = logging.getLogger(__name__)


class ApsApiClientCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(self, hass, session, username, password):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="APS API client coordinator",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(minutes=5),
        )
        self.api = ApsApi(session, username, password)

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            # # Note: asyncio.TimeoutError and aiohttp.ClientError are already
            # # handled by the data update coordinator.
            # _LOGGER.warn(f"_async_update_data called!")
            statistics = {}
            await self.api.login()

            summary_data = await self.api.get_summary()
            if summary_data == "no data":
                statistics["system_capacity"] = None
                statistics["lifetime_co2_kg"] = None
                statistics["month_total_kwh"] = None
                statistics["current_power"] = None
                statistics["today_total_kwh"] = None
                statistics["lifetime_total_kwh"] = None
                statistics["tree_years"] = None
                statistics["year_total_kwh"] = None
            else:
                statistics["system_capacity"] = summary_data["capacity"]
                statistics["lifetime_co2_kg"] = summary_data["co2"]
                statistics["month_total_kwh"] = summary_data["month"]
                statistics["current_power"] = summary_data["power"]
                statistics["today_total_kwh"] = summary_data["today"]
                statistics["lifetime_total_kwh"] = summary_data["total"]
                statistics["tree_years"] = summary_data["tree"]
                statistics["year_total_kwh"] = summary_data["year"]

            todays_data = await self.api.get_production_for_day()
            if todays_data == "no data":
                # statistics["current_power"] = 0
                # statistics["today_total_kwh"] = 0
                statistics["today_co2_kg"] = 0
            else:
                # statistics["current_power"] = todays_data["power"][-1],
                # statistics["today_total_kwh"] = todays_data["total"],
                statistics["today_co2_kg"] = todays_data["co2"]

            _LOGGER.debug("FINAL STATS")
            _LOGGER.debug(statistics)
            return statistics
        except ApiAuthError as err:
            # Raising ConfigEntryAuthFailed will cancel future updates
            # and start a config flow with SOURCE_REAUTH (async_step_reauth)
            raise ConfigEntryAuthFailed from err
        except Exception as err:
            _LOGGER.warn(
                "an exception occured during data update. Error was:", err)
            # raise UpdateFailed("Error communicating with APS API.")
