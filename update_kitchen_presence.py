#!/usr/bin/env python3
"""Update kitchen_presence template sensor to also check office sensor entities."""
import sys

with open("/config/configuration.yaml", "r") as f:
    content = f.read()

# Current template sensor state definition
old = """        state: >
          {{ is_state('binary_sensor.kitchen_mmwave_presence_sensor_presence', 'on')
             or (states('sensor.kitchen_mmwave_presence_sensor_moving_distance') | float(-1) > 0)
             or is_state('input_boolean.nest_kitchen_presence', 'on') }}"""

# New version with office sensor entities added
new = """        state: >
          {{ is_state('binary_sensor.kitchen_mmwave_presence_sensor_presence', 'on')
             or (states('sensor.kitchen_mmwave_presence_sensor_moving_distance') | float(-1) > 0)
             or is_state('binary_sensor.usb_c_mmwave_sensor_presence', 'on')
             or (states('sensor.usb_c_mmwave_sensor_moving_distance') | float(-1) > 0)
             or is_state('input_boolean.nest_kitchen_presence', 'on') }}"""

if old in content:
    content = content.replace(old, new)
    with open("/config/configuration.yaml", "w") as f:
        f.write(content)
    print("SUCCESS: Template sensor updated to include office sensor entities")
else:
    print("ERROR: Could not find the exact old template sensor text in configuration.yaml")
    # Try to find what's actually there
    import re
    m = re.search(r'state: >\n\s+\{\{.*?nest_kitchen_presence.*?\}\}', content, re.DOTALL)
    if m:
        matched = m.group()
        print(f"Found actual text (char diff from expected):")
        print(repr(matched))
    else:
        print("Could not find any matching template sensor pattern")
