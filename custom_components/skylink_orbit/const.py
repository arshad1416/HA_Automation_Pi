"""Constants for the Skylink Orbit Garage Door integration."""

from datetime import timedelta

DOMAIN = "skylink_orbit"
PLATFORMS = ["cover", "binary_sensor"]

# Config keys
CONF_USERNAME = "username"
CONF_BASE_URL = "base_url"
CONF_ACC_NO = "acc_no"
CONF_HUB_IDS = "hub_ids"

# Real API base URL (discovered via mitmproxy)
DEFAULT_BASE_URL = "https://iot.skyhm.net:8444/skylinkhub_crm/skyhm_api_s.jsp"

# Signing secret (extracted from APK: HeadInterceptor.intercept())
# Signature = MD5(timestamp + "+" + cmd + "+" + reqData + "+8uHDSF77ueRmLlKkl67").lower()
SIGNING_SECRET = "+8uHDSF77ueRmLlKkl67"

# API command names (sent as ?cmd= query param and REQ-CMD header)
CMD_LOGIN = "act_login"
CMD_GET_FIRMWARE = "get_last_firmware"
CMD_HUB_ADD = "hub_add"
CMD_HUB_DEL = "hub_del"
CMD_HUB_EVENT_LOG = "hub_event_log"
CMD_HUB_IMPORT = "hub_import"
CMD_HUB_ADD_PNTF = "hub_add_pntf"
CMD_HUB_DEL_PNTF = "hub_del_pntf"
CMD_HUB_ADD_SUP = "hub_add_sup"
CMD_HUB_DEL_SUP = "hub_del_sup"
CMD_ACT_NEW = "act_new"
CMD_ACT_NEW_VERIFY = "act_new_verify"
CMD_ACT_RESEND = "act_resend"
CMD_ACT_CHG_PWD = "act_chg_pwd"
CMD_ACT_RESET_PWD = "act_reset_pwd"
CMD_ACT_DEL = "act_del"
CMD_ACT_DEL_PN_TOKEN = "act_del_pn_token"
CMD_ACT_HUB_GRANT = "act_hub_grant"
CMD_GET_APP_VERSION = "get_app_version"
CMD_CAM_ADD = "cam_add"
CMD_CAM_DEL = "cam_del"
CMD_CAM_CHG_NAME = "cam_chg_name"
CMD_CAM_CHG_PWD = "cam_chg_pwd"
CMD_SET_ALEXA_PIN = "set_alexa_pin"
CMD_SET_AOG_PIN = "set_aog_pin"

# App identification (from captured User-Agent and login payload)
APP_USER_AGENT = "Orbit/3.4 (iPhone; iOS 26.3; Scale/3.00)"
APP_SYS = "apns"       # Apple Push Notification Service
APP_BRAND = "00"        # Skylink brand identifier

# MQTT broker (extracted from APK: MainActivity.initMqtt())
MQTT_BROKER_HOST = "34.214.223.70"
MQTT_BROKER_PORT = 1899
MQTT_BROKER_URL = f"ssl://{MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}"
MQTT_KEEPALIVE = 30
MQTT_CONNECT_TIMEOUT = 180

# MQTT topic templates (extracted from APK: MainActivity.<init>())
# Topics use pattern: skylink/things/client/{acc_no}/{suffix}
MQTT_TOPIC_BASE = "skylink/things/client"
MQTT_TOPIC_GET_RESULT = "{base}/{acc_no}/get/result"       # Subscribe: state responses
MQTT_TOPIC_GET = "{base}/{acc_no}/get"                     # Publish: request state
MQTT_TOPIC_UPDATE_RESULT = "{base}/{acc_no}/update/result" # Subscribe: state updates
MQTT_TOPIC_DESIRE = "{base}/{acc_no}/desire"               # Publish: send commands

# MQTT door control command (extracted from APK: MainActivity.deviceContral())
# GDO (garage door opener) JSON payload:
#   {"data":{"hub_id":"<hub_id>","desired":{"mdev":{"ctrlgdo":{"cmd":<int>,"ts":"<ms>"}}}}}
# With position (NOVA devices):
#   {"data":{"hub_id":"<hub_id>","desired":{"mdev":{"ctrlgdo":{"cmd":<int>,"ts":"<ms>","position":"<A|B>"}}}}}
# cmd value is 0 for toggle (from contralDoor: v9=0 for GDO type)
MQTT_GDO_CMD_TOGGLE = 0

# Polling interval for device state updates
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)

# Door states (from APK string analysis)
DOOR_STATE_OPEN = "open"
DOOR_STATE_CLOSED = "closed"
DOOR_STATE_OPENING = "opening"
DOOR_STATE_CLOSING = "closing"
DOOR_STATE_STOPPED = "stopped"
DOOR_STATE_UNKNOWN = "unknown"
