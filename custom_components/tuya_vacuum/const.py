"""Constants for Tuya Vacuum Local integration."""

DOMAIN = "tuya_vacuum"

CONF_DEVICE_ID      = "device_id"
CONF_DEVICE_IP      = "device_ip"
CONF_DEVICE_KEY     = "device_key"
CONF_DEVICE_VERSION = "device_version"
CONF_CLIENT_ID      = "tuya_client_id"
CONF_CLIENT_SECRET  = "tuya_client_secret"
CONF_REGION         = "tuya_region"

REGIONS = {
    "eu": "https://openapi.tuyaeu.com",
    "us": "https://openapi.tuyaus.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}

# Tuya vacuum DP IDs
DP_POWER        = 1
DP_PAUSE        = 2
DP_CHARGE       = 3
DP_MODE         = 4
DP_STATUS       = 5
DP_CLEAN_TIME   = 6
DP_CLEAN_AREA   = 7
DP_BATTERY      = 8
DP_SUCTION      = 9
DP_WATER        = 10
DP_LOCATE       = 11
DP_REQUEST      = 16   # "get_both" triggers map push
DP_COMMAND_TRANS = 15  # binary command channel (map frames + control)

SUCTION_LEVELS = ["gentle", "normal", "strong", "strong_plus"]
WATER_LEVELS   = ["closed", "low", "middle", "high"]

# DP4 mode values
MODE_SMART     = "smart"
MODE_ZONE      = "zone"
MODE_SPOT      = "pose"
MODE_ROOM      = "selectroom"
MODE_CHARGE    = "chargego"

# Room cell values in map grid
ROOM_CELL_VALUES = [0x00, 0x04, 0x08, 0x0C, 0x10]

# Update interval for coordinator (seconds)
UPDATE_INTERVAL = 30

# Map refresh delay after cleaning ends
MAP_REFRESH_DELAY = 15
