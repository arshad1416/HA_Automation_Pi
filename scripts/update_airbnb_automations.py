#!/usr/bin/env python3
"""
Update Airbnb check-in/check-out automations to use configurable input_datetime
helpers instead of hardcoded offsets. Also adds input_datetime to configuration.yaml.

Run inside the HA Docker container:
    docker exec -i homeassistant python3 /config/scripts/update_airbnb_automations.py
"""

import re
import sys
import yaml

def update_configuration_yaml(content: str) -> str:
    """Add input_datetime section to configuration.yaml if not present."""
    if 'input_datetime:' in content:
        print("input_datetime already exists in configuration.yaml, checking for airbnb entries...")
        if 'airbnb_check_in_time' in content:
            print("  airbnb_check_in_time already present — skipping addition")
            return content
        # Insert airbnb entries under existing input_datetime
        input_datetime_block = """input_datetime:
  airbnb_check_in_time:
    name: Airbnb Check-In Time
    has_date: false
    has_time: true
    initial: "15:00"
    icon: mdi:door-open
  airbnb_check_out_time:
    name: Airbnb Check-Out Time
    has_date: false
    has_time: true
    initial: "14:00"
    icon: mdi:door-closed
"""
        # Find existing input_datetime: and add after it
        idx = content.find('input_datetime:')
        end = content.find('\n', idx)
        # Find the next top-level key (no indentation)
        next_key_match = re.search(r'\n[a-z]', content[end:])
        if next_key_match:
            insert_pos = end + next_key_match.start()
        else:
            insert_pos = len(content)
        content = content[:insert_pos] + '\n' + input_datetime_block + content[insert_pos:]
        return content

    # Add input_datetime before input_boolean
    new_section = """input_datetime:
  airbnb_check_in_time:
    name: Airbnb Check-In Time
    has_date: false
    has_time: true
    initial: "15:00"
    icon: mdi:door-open
  airbnb_check_out_time:
    name: Airbnb Check-Out Time
    has_date: false
    has_time: true
    initial: "14:00"
    icon: mdi:door-closed

"""

    # Insert before input_boolean:
    if '\ninput_boolean:' in content:
        content = content.replace('\ninput_boolean:', '\n' + new_section + 'input_boolean:')
    elif '\ninput_text:' in content:
        content = content.replace('\ninput_text:', '\n' + new_section + 'input_text:')
    else:
        # Append at end
        content = content.rstrip() + '\n\n' + new_section

    return content


def update_automations_yaml(content: str) -> str:
    """Replace all airbnb_* automations with updated versions using input_datetime."""

    new_airbnb_automations = """- id: airbnb_reserved_sync
  alias: 'Airbnb: Reserved Flag Sync'
  description: 'Keeps switch.airbnb_reserved in sync with calendar.airbnb_ics state — on when reservation active, off when vacant. Fires on HA start to recover from restarts during iCal sync gaps.'
  mode: restart
  triggers:
  - trigger: calendar
    entity_id: calendar.airbnb_ics
    event: start
  - trigger: calendar
    entity_id: calendar.airbnb_ics
    event: end
  - trigger: homeassistant
    event: start
  conditions: []
  actions:
  - if:
    - condition: template
      value_template: "{{ is_state('calendar.airbnb_ics','on') and 'reserved' in (state_attr('calendar.airbnb_ics','message') | string | lower) }}"
    then:
    - action: switch.turn_on
      target: {entity_id: switch.airbnb_reserved}
    else:
    - action: switch.turn_off
      target: {entity_id: switch.airbnb_reserved}
- id: airbnb_sunset_logic
  alias: 'Airbnb: Sunset Logic'
  description: 'At sunset: reservation active NOW -> floodlight ON (scene.manual_on); otherwise motion-sensor mode (scene.sensor_mode). Does NOT touch the heater, preserving guest manual control. Uses is_state(calendar,on) because the message attribute leaks the NEXT upcoming event on vacant days.'
  mode: single
  triggers:
  - trigger: sun
    event: sunset
    offset: 0
  conditions: []
  actions:
  - if:
    - condition: template
      value_template: "{{ is_state('calendar.airbnb_ics','on') and 'reserved' in (state_attr('calendar.airbnb_ics','message') | string | lower) }}"
    then:
    - action: scene.turn_on
      target: {entity_id: scene.manual_on}
    else:
    - action: scene.turn_on
      target: {entity_id: scene.sensor_mode}
- id: airbnb_midnight_logic
  alias: 'Airbnb: Midnight Logic'
  description: 'Every midnight: floodlight back to motion-sensor mode and off. Unconditional — safe on non-reserved nights and covers the final-night calendar rollover.'
  mode: single
  triggers:
  - trigger: time
    at: '00:00:00'
  conditions: []
  actions:
  - action: scene.turn_on
    target: {entity_id: scene.sensor_mode}
  - action: light.turn_off
    target: {entity_id: light.wasserstein_smart_floodlight_2}
- id: airbnb_checkin
  alias: 'Airbnb: Check-in (heater on)'
  description: 'Calendar reservation start -> set reserved flag -> delay until configurable check-in time (input_datetime.airbnb_check_in_time, default 15:00) -> heater to heat at helper temp. Safety sync at 15:30 is the backstop for HA restarts.'
  mode: single
  triggers:
  - trigger: calendar
    entity_id: calendar.airbnb_ics
    event: start
  conditions:
  - condition: template
    value_template: "{{ 'reserved' in (trigger.calendar_event.summary | lower) }}"
  actions:
  - action: switch.turn_on
    target: {entity_id: switch.airbnb_reserved}
  - delay:
      seconds: "{{ [0, (today_at(states('input_datetime.airbnb_check_in_time')) - now()).total_seconds() | int] | max }}"
  - action: climate.set_hvac_mode
    target: {entity_id: climate.airbnb_infrared_heater_2}
    data: {hvac_mode: heat}
    continue_on_error: true
  - action: climate.set_temperature
    target: {entity_id: climate.airbnb_infrared_heater_2}
    data: {temperature: "{{ states('input_number.airbnb_heater_temperature') | float(20) }}"}
    continue_on_error: true
  - action: notify.mobile_app_cph2655
    data:
      message: "Airbnb check-in: heater commanded to heat at {{ states('input_number.airbnb_heater_temperature') | int(20) }}°C — now reporting {{ states('climate.airbnb_infrared_heater_2') }} / {{ state_attr('climate.airbnb_infrared_heater_2','temperature') }}°C."
- id: airbnb_checkout
  alias: 'Airbnb: Checkout (heater off, floodlight to sensor mode)'
  description: 'Calendar reservation end -> delay until configurable check-out time (input_datetime.airbnb_check_out_time, default 14:00) -> heater off, floodlight off and back to motion-sensor mode, reserved flag off. A same-day new reservation re-arms via Check-in.'
  mode: single
  triggers:
  - trigger: calendar
    entity_id: calendar.airbnb_ics
    event: end
  conditions:
  - condition: template
    value_template: "{{ 'reserved' in (trigger.calendar_event.summary | lower) }}"
  actions:
  - delay:
      seconds: "{{ [0, (today_at(states('input_datetime.airbnb_check_out_time')) - now()).total_seconds() | int] | max }}"
  - action: climate.set_hvac_mode
    target: {entity_id: climate.airbnb_infrared_heater_2}
    data: {hvac_mode: 'off'}
  - action: scene.turn_on
    target: {entity_id: scene.sensor_mode}
  - action: light.turn_off
    target: {entity_id: light.wasserstein_smart_floodlight_2}
  - action: switch.turn_off
    target: {entity_id: switch.airbnb_reserved}
  - action: notify.mobile_app_cph2655
    data:
      message: 'Airbnb checkout: heater off, floodlight returned to motion-sensor mode, reserved flag cleared.'
- id: airbnb_heater_safety_sync
  alias: 'Airbnb: Heater Safety Sync'
  description: 'Daily 15:30 backstop for calendar triggers missed during HA downtime or late iCal syncs. Vacant + heater not off -> off. Check-in-day reservation active + heater still off -> one-shot re-arm (start date must be today, so guest manual-off later in the stay is never overridden). Uses is_state(calendar,on) because the message attribute leaks the NEXT event when vacant.'
  mode: single
  triggers:
  - trigger: time
    at: '15:30:00'
  conditions: []
  actions:
  - choose:
    - conditions:
      - condition: template
        value_template: "{{ not (is_state('calendar.airbnb_ics','on') and 'reserved' in (state_attr('calendar.airbnb_ics','message') | string | lower)) }}"
      - condition: not
        conditions:
        - condition: state
          entity_id: climate.airbnb_infrared_heater_2
          state: 'off'
      sequence:
      - action: climate.set_hvac_mode
        target: {entity_id: climate.airbnb_infrared_heater_2}
        data: {hvac_mode: 'off'}
      - action: notify.mobile_app_cph2655
        data:
          message: 'Airbnb safety sync: heater was on with no reservation — turned off.'
    - conditions:
      - condition: template
        value_template: "{{ is_state('calendar.airbnb_ics','on') and 'reserved' in (state_attr('calendar.airbnb_ics','message') | string | lower) }}"
      - condition: state
        entity_id: climate.airbnb_infrared_heater_2
        state: 'off'
      - condition: template
        value_template: "{{ (state_attr('calendar.airbnb_ics','start_time') | as_datetime | as_local).date() == now().date() }}"
      sequence:
      - action: climate.set_hvac_mode
        target: {entity_id: climate.airbnb_infrared_heater_2}
        data: {hvac_mode: heat}
        continue_on_error: true
      - action: climate.set_temperature
        target: {entity_id: climate.airbnb_infrared_heater_2}
        data: {temperature: "{{ states('input_number.airbnb_heater_temperature') | float(20) }}"}
        continue_on_error: true
      - action: notify.mobile_app_cph2655
        data:
          message: 'Airbnb safety sync: check-in day but heater was off (missed 3 PM trigger?) — re-armed to heat.'
"""

    # Find all airbnb automation blocks
    # Strategy: find the first "- id: airbnb_" and replace through the last airbnb block
    airbnb_ids = [
        'airbnb_sunset_logic',
        'airbnb_midnight_logic',
        'airbnb_checkin',
        'airbnb_checkout',
        'airbnb_heater_safety_sync',
    ]

    # Find the start of the first Airbnb automation
    first_idx = content.find('- id: airbnb_sunset_logic')
    if first_idx == -1:
        # Try alternate format (some files put actions first)
        first_idx = content.find('alias: \'Airbnb:')
        if first_idx == -1:
            print("ERROR: Could not find Airbnb automations in 01_main.yaml")
            sys.exit(1)

    # Find the start of the line containing the first Airbnb automation
    # Go back to the start of the "- id:" or "- actions:" line
    line_start = content.rfind('\n', 0, first_idx) + 1

    # Find the end of the last Airbnb automation block
    # The last one is airbnb_heater_safety_sync
    last_id = 'airbnb_heater_safety_sync'
    last_idx = content.find('airbnb_heater_safety_sync')
    if last_idx == -1:
        print("ERROR: Could not find airbnb_heater_safety_sync")
        sys.exit(1)

    # Find the next "- id:" or "- actions:" after the last Airbnb automation block
    # This marks the end of the Airbnb automations section
    search_from = last_idx + len(last_id)
    next_block_match = re.search(r'\n- (?:id:|actions:)', content[search_from:])
    if next_block_match:
        end_pos = search_from + next_block_match.start()
    else:
        end_pos = len(content)

    # Build the new content
    old_section = content[line_start:end_pos]
    print(f"Replacing {len(old_section)} chars of Airbnb automations (lines starting at char {line_start})")

    # Preserve leading newline format
    new_content = content[:line_start] + new_airbnb_automations.rstrip() + content[end_pos:]

    return new_content


def main():
    # --- Update configuration.yaml ---
    config_path = '/config/configuration.yaml'
    print(f"Reading {config_path}...")
    with open(config_path, 'r') as f:
        config_content = f.read()

    print(f"  Original length: {len(config_content)} chars")

    # Backup
    with open(config_path + '.bak', 'w') as f:
        f.write(config_content)
    print(f"  Backup written to {config_path}.bak")

    new_config = update_configuration_yaml(config_content)
    print(f"  New length: {len(new_config)} chars")

    with open(config_path, 'w') as f:
        f.write(new_config)
    print(f"  Written {config_path}")

    # --- Update 01_main.yaml ---
    auto_path = '/config/automations/01_main.yaml'
    print(f"\nReading {auto_path}...")
    with open(auto_path, 'r') as f:
        auto_content = f.read()

    print(f"  Original length: {len(auto_content)} chars")

    # Backup
    with open(auto_path + '.bak', 'w') as f:
        f.write(auto_content)
    print(f"  Backup written to {auto_path}.bak")

    new_auto = update_automations_yaml(auto_content)
    print(f"  New length: {len(new_auto)} chars")

    with open(auto_path, 'w') as f:
        f.write(new_auto)
    print(f"  Written {auto_path}")

    # --- Verify YAML parses ---
    print("\nVerifying YAML parse...")
    try:
        with open(config_path) as f:
            yaml.safe_load(f)
        print("  configuration.yaml: OK")
    except Exception as e:
        print(f"  configuration.yaml: PARSE ERROR: {e}")
        # Restore backup
        with open(config_path, 'w') as f:
            f.write(config_content)
        print("  Restored configuration.yaml from backup")

    try:
        with open(auto_path) as f:
            yaml.safe_load(f)
        print("  01_main.yaml: OK")
    except Exception as e:
        print(f"  01_main.yaml: PARSE ERROR: {e}")
        # Restore backup
        with open(auto_path, 'w') as f:
            f.write(auto_content)
        print("  Restored 01_main.yaml from backup")

    print("\nDone. Run check_config to verify.")


if __name__ == '__main__':
    main()