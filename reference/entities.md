# Discovered HA Entity IDs

Discovered 2026-04-26 by querying `/config/.storage/core.entity_registry` on the Pi. Used by the proactive automations.

## Person
- `person.home` — Arshad (note: literal entity_id `person.home`, not `person.arshad`)
- `person.larissa` — Larissa

## Calendars
- `calendar.arshad14_gmail_com` — primary personal (Arshad14@gmail.com) ← used in welcome-home
- `calendar.https_www_airbnb_ca_calendar_ical_...` — Airbnb reservations (existing automation)
- `calendar.shared`, `calendar.family`, `calendar.work`, etc. — others

## Echos (alexa_media platform)
- `media_player.downstairs_echo_dot` — used for door reminder + welcome-home
- `media_player.upstairs_echo_dot` — used for nightly lock check
- `media_player.echo_dot`
- `media_player.mina_s_echo_dot`
- `media_player.izaan_s_echo_dot`
- `media_player.mummie_papa_s_echo_show_5_2nd_gen`
- `media_player.everywhere` — virtual group (broadcast)

## Locks
- `lock.front_door`
- `lock.garages_entry_door`
- `lock.airbnb` ← excluded from nightly check (separate suite/property)

## Door sensors
- `binary_sensor.front_door_door` ← used in door-left-open automation
- `binary_sensor.garages_entry_door_door`
- `binary_sensor.airbnb_door`

## Weather
- `weather.forecast_home` — Home weather (Met.no integration). Use `state_attr('weather.forecast_home','temperature')` for current temp; no dedicated outdoor temp sensor was found.

## Notification service
- `notify.alexa_media` — pushes TTS announcements to any Echo via `data: {type: announce}`
