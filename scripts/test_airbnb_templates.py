#!/usr/bin/env python3
"""Test the Airbnb delay templates via the HA template API.

Usage:  HA_TOKEN=<long-lived-token> python3 scripts/test_airbnb_templates.py
"""
import json
import os
import sys
import urllib.request

# 2026-08-09: was a hardcoded refresh token + /auth/token exchange. A long-lived token works
# directly, so the exchange is gone. Same HA_TOKEN env var as verification/smoke-tests.sh.
token = os.environ.get('HA_TOKEN')
if not token:
    try:
        import pytest  # being collected by pytest — skip this script, don't kill the suite
        pytest.skip('HA_TOKEN not set — see file docstring for usage')
    except ImportError:
        sys.exit('HA_TOKEN not set — create a long-lived access token in HA '
                 '(Profile → Security → Long-lived access tokens), then:\n'
                 '  HA_TOKEN=<token> python3 scripts/test_airbnb_templates.py')

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