#!/usr/bin/env python3
"""Test the Airbnb delay templates via the HA template API."""
import json
import urllib.request
import urllib.parse

# Get token
token_req = urllib.request.Request(
    'http://localhost:8123/auth/token',
    data=urllib.parse.urlencode({
        'grant_type': 'refresh_token',
        'refresh_token': 'db5adb443f6675591d50e04bc8d21b514cc24bc5fc1db980fba9868ecf0ed942e347143a6dfbc19bc32138847854be2ba916e40690aeb0fc8501169949841999'
    }).encode(),
    method='POST')
with urllib.request.urlopen(token_req) as r:
    token = json.loads(r.read())['access_token']

headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

# Test check-in delay template
t_checkin = "{{ [0, (today_at(states('input_datetime.airbnb_check_in_time')) - now()).total_seconds() | int] | max }}"
data = json.dumps({'template': t_checkin}).encode()
req = urllib.request.Request('http://localhost:8123/api/template', data=data, headers=headers, method='POST')
with urllib.request.urlopen(req) as r:
    result = r.read().decode()
    print(f'Check-in delay (seconds): {result}')

# Test check-out delay template
t_checkout = "{{ [0, (today_at(states('input_datetime.airbnb_check_out_time')) - now()).total_seconds() | int] | max }}"
data = json.dumps({'template': t_checkout}).encode()
req = urllib.request.Request('http://localhost:8123/api/template', data=data, headers=headers, method='POST')
with urllib.request.urlopen(req) as r:
    result = r.read().decode()
    print(f'Check-out delay (seconds): {result}')

# Test the state values
t_state = "{{ states('input_datetime.airbnb_check_in_time') }}"
data = json.dumps({'template': t_state}).encode()
req = urllib.request.Request('http://localhost:8123/api/template', data=data, headers=headers, method='POST')
with urllib.request.urlopen(req) as r:
    result = r.read().decode()
    print(f'Check-in time state: {result}')

t_state2 = "{{ states('input_datetime.airbnb_check_out_time') }}"
data = json.dumps({'template': t_state2}).encode()
req = urllib.request.Request('http://localhost:8123/api/template', data=data, headers=headers, method='POST')
with urllib.request.urlopen(req) as r:
    result = r.read().decode()
    print(f'Check-out time state: {result}')