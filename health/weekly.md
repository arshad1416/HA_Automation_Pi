# Home Assistant weekly health — 2026-10-05 23:25

## System
- Pi CPU 67.2°C · disk 118 GB used, 1749 GB free · recorder DB 563 MB
- Recorder history reaches back 7.8 days

## Unavailable entities: 323 (previous run: n/a)
New since last run: 0

## Top availability flaps (7 days)
- 1195 · light.island_light_kitchen_island_light
- 1195 · select.island_light_light_source_type
- 432 · sensor.3d_printer_energy_monitoring_sm_voltage
- 431 · sensor.3d_printer_energy_monitoring_sm_current
- 431 · sensor.3d_printer_energy_monitoring_sm_power
- 431 · sensor.3d_printer_energy_monitoring_sm_energy
- 431 · switch.3d_printer_energy_monitoring_sm_switch
- 342 · image.player086460299_gamerpic
- 342 · image.player086460299_now_playing
- 342 · image.player086460299_avatar
- 341 · binary_sensor.player086460299
- 341 · binary_sensor.player086460299_in_game
- 341 · binary_sensor.player086460299_subscribed_to_xbox_game_pass
- 341 · sensor.player086460299_status
- 341 · sensor.player086460299_gamerscore

## Automations that fired the week before but not this week
- not enough history yet (needs 14 days)

## Batteries below 30%
- 19% · sensor.z60_ultra_roller_complete_battery_level
- 28% · sensor.airbnb_battery
- 28% · sensor.airbnb_door_battery

## Top log warnings/errors (current home-assistant.log)
- 22 · WARNING · homeassistant.loader · We found a custom integration govee which has not been tested by Home Assistant. This component might cause stability problems, be sure to d
- 9 · WARNING · aiohomekit.controller.coap.pdu · Transaction 0 failed with error 6 (Invalid request
- 5 · WARNING · homeassistant.helpers.sun · The deprecated function get_astral_location was called from illuminance. It will be removed in HA Core 2027.7. Use homeassistant.helpers.sun
- 5 · WARNING · homeassistant.components.sensor · Entity sensor.solar_credits_today (<class 'homeassistant.components.command_line.sensor.CommandSensor'>) is using state class 'total_increas
- 5 · WARNING · homeassistant.util.loop · Detected blocking call to load_default_certs with args (<ssl.SSLContext object at 0x53f21539920>, <Purpose.SERVER_AUTH: _ASN1Object(nid=129,
- 4 · WARNING · homeassistant.const · The deprecated constant CONCENTRATION_MICROGRAMS_PER_CUBIC_METER was used from sonoff. It will be removed in HA Core 2027.8. Use UnitOfDensi
- 4 · WARNING · custom_components.wyzeapi.camera · Error fetching WebRTC session configuration for camera Handy Cam: Camera is offline according to get_stream_info response: {'property': {'io
- 2 · WARNING · homeassistant.components.recorder.util · The system could not validate that the sqlite3 database at //config/home-assistant_v2.db was shutdown cleanly
- 2 · WARNING · homeassistant.config_entries · Config entry 'SHIELD' for androidtv_remote integration could not authenticate: Need to pair again
- 2 · WARNING · hyundai_kia_connect_api.KiaUvoApiCA · hyundai_kia_connect_api - Get vehicle location failed
- 2 · WARNING · custom_components.localtuya.coordinator · [eb7...hi7 - Massage Room Heater] Connection failed: [Errno 113] Host is unreachable ('<ip>', '6668')
- 2 · WARNING · aioesphomeapi.reconnect_logic · Can't connect to ESPHome API for master-bedroom-mmwave @ <ip>: Error connecting to [AddrInfo(family=<AddressFamily.AF_INET: 2>, type=<Socket
