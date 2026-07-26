import json
import logging
from datetime import datetime
from urllib.parse import urlencode
import aiohttp
from .const import BASE_API_URL
from .utils import add_hmac_signature

_LOGGER = logging.getLogger(__name__)


class ApsApi:
    def __init__(self, session: aiohttp.ClientSession, username: str, password: str):
        # body of the constructor
        self.session = session
        self.username = username
        self.password = password
        self.accessToken = ""
        self.openId = ""
        self.login_result = []
        return None

    async def __apiCall(self, request_without_hmac, url):
        """the actual API caller"""
        request_body = add_hmac_signature(request_without_hmac)
        encoded = urlencode(request_body)
        _LOGGER.debug("calling %s", url)
        _LOGGER.debug("payload %s", encoded)
        resp = await self.session.post(
            url=url,
            data=f"{encoded}",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        jsonstr = await resp.text()
        _LOGGER.debug("call result: %s", jsonstr)
        result = json.loads(jsonstr)
        return result

    # all starts here
    async def login(self):
        """logs in to API"""
        request_body = {
            "username": self.username,
            "password": self.password,
            "language": "en_US",
            "type": "0",
            "apiuser": "appA",
        }
        data = await self.__apiCall(
            request_body, f"{BASE_API_URL}/view/registration/user/checkUser"
        )

        if data["message"] == "Invalid Request":
            raise ApiAuthError("Failed to authenticate")
        if data["message"] != "Succeed to login":
            raise ApiAuthError("Unknown error occured")

        self.accessToken = data["data"]["access_token"]
        self.openId = data["data"]["openId"]
        self.login_result = data["data"]
        return data

    # necessary calls: login -> this
    async def get_ecu_info(self):
        """fetches ecu info (we need ecu ID)"""
        request_body = {
            "access_token": self.accessToken,
            "openId": self.openId,
            "language": "en_US",
            "userId": self.login_result["system"]["user_id"],
            "apiuser": "appA",
        }
        data = await self.__apiCall(
            request_body, f"{BASE_API_URL}/view/registration/ecu/getEcuInfoBelowUser"
        )
        return list(data["data"].values())[0]

    async def get_summary(self):
        """fetches summarized statistics"""

        try:
            request_body = {
                "access_token": self.accessToken,
                "openId": self.openId,
                "language": "en_US",
                "apiuser": "appA",
                "userId": self.login_result["system"]["user_id"],
            }
            result = await self.__apiCall(
                request_body,
                f"{BASE_API_URL}/view/production/user/getSummaryProductionForEachSystem",
            )
            _LOGGER.debug("summary result")
            _LOGGER.debug(result)
            if result.get("data", False) is False:
                return "no data"
            return list(result["data"].values())[0]
        except Exception as err:
            return "no data"

    #   "data": {
    #      "1234567890abcdef": {
    #         "capacity": "1234", # watts
    #         "co2": "1234.123", # lifetime co2 reduction
    #         "duration": "123", # ???
    #         "month": "123.456", # month's generated kwh
    #         "power": "1234.5678", # current power production in watts
    #         "today": "12.3456, # today's generated kwh
    #         "total": "1234.5678", total generated kwh
    #         "tree": "123.456", # 1 tree = 20 kg co2 / year
    #         "type": 0, # ???
    #         "year": "1234.1234" # year's generated kwh
    #      }
    #   },

    # necessary calls: login -> getEcuInfo -> this
    async def get_production_for_day(self):
        """fetches production data for a day"""
        datestring = datetime.now().strftime("%Y%m%d")
        ecudata = await self.get_ecu_info()
        request_body = {
            "date": datestring,
            "access_token": self.accessToken,
            "systemId": self.login_result["system"]["system_id"],
            "openId": self.openId,
            "language": "en_US",
            "ecuId": ecudata["ecuId"],
            "apiuser": "appA",
        }
        result = await self.__apiCall(
            request_body, f"{BASE_API_URL}/view/production/ecu/getPowerOnCurrentDay"
        )
        _LOGGER.debug("productionForDay result")
        _LOGGER.debug(result)
        return result.get("data", "no data")
        # "data":{
        #     "duration":123, # ???
        #     "total":"12.3456", # kwh
        #     "max":"1234.5", # watts
        #     ...
        #     ],
        #     "co2":"12.3456", # kgs
        #     "time":[ # timestamp-string[]
        #     ...
        #     ],
        #     "power":[ # watts-string[]
        #     ...
        #     ],
        #     "energy":[ # kwh-string[] (from the last 5 minutes?)
        #     ...
        #     ]
        # },


class ApiAuthError(Exception):
    """just a custom error"""
