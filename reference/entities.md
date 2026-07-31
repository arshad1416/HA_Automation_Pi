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

## EV Per-Vehicle Cost Tracking

### Input Numbers (cost/energy accumulators)
- `input_number.ioniq_6_total_cost_cents` — Ioniq 6 lifetime charging cost (cents)
- `input_number.vf9_total_cost_cents` — VF9 lifetime charging cost (cents)
- `input_number.ioniq_6_total_energy_kwh` — Ioniq 6 lifetime charging energy (kWh)
- `input_number.vf9_total_energy_kwh` — VF9 lifetime charging energy (kWh)
- `input_number.ev_session_soc_start_ioniq` — Ioniq SoC at session start (%)
- `input_number.ev_session_soc_start_vf9` — VF9 SoC at session start (%)
- `input_number.ev_fixed_cost_accumulated_cents` — Accumulated fixed delivery charges (cents)
- `input_number.ev_unknown_cost_cents` — Unattributed session costs (cents)

### Input Text
- `input_text.ev_session_vehicle` — Detected vehicle for current/last session ("ioniq_6", "vf9", "unknown", "detecting")

### Template Sensors
- `sensor.ev_charging_vehicle_detected` — Vehicle detection (states: ioniq_6, vf9, unknown, inactive)
- `sensor.ev_ioniq_6_total_cost` — Ioniq 6 total cost (CAD, state_class: total_increasing)
- `sensor.ev_vf9_total_cost` — VF9 total cost (CAD, state_class: total_increasing)
- `sensor.ev_ioniq_6_total_energy` — Ioniq 6 total energy (kWh, state_class: total_increasing)
- `sensor.ev_vf9_total_energy` — VF9 total energy (kWh, state_class: total_increasing)
- `sensor.ev_fixed_cost_total` — Fixed delivery cost total (CAD, state_class: total_increasing)

### Utility Meters
- `sensor.ioniq_6_cost_daily` — Ioniq 6 cost daily rollup
- `sensor.ioniq_6_cost_monthly` — Ioniq 6 cost monthly rollup
- `sensor.vf9_cost_daily` — VF9 cost daily rollup
- `sensor.vf9_cost_monthly` — VF9 cost monthly rollup
- `sensor.ioniq_6_energy_daily` — Ioniq 6 energy daily rollup
- `sensor.ioniq_6_energy_monthly` — Ioniq 6 energy monthly rollup
- `sensor.vf9_energy_daily` — VF9 energy daily rollup
- `sensor.vf9_energy_monthly` — VF9 energy monthly rollup

### Automations (08_ev_per_vehicle_cost_tracking.yaml)
- `ev_session_start_record_soc` — Records SoC baselines at charging start
- `ev_session_end_attribute_cost` — Attributes session cost to detected vehicle
- `ev_monthly_reconciliation` — Monthly fixed cost proportional split
- `ev_cost_tracking_diagnostics` — Hourly diagnostic logging during active charging
