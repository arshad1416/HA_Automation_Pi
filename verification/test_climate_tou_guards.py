#!/usr/bin/env python3
"""Self-check for the 2026-09-05 climate TOU guards.

Renders the real Jinja from the automation YAML with a stub of the handful of
HA template functions they use, and asserts the four audited behaviours:

  1. evening_comfort_setpoint skips the write during live On-Peak.
  2. climate_ai_advisor has a tariff_change trigger (the 16:00 race fix).
  3. The on-peak floor forces 25.5C and exempts that raise from the 2 h hold,
     but stays out of the way at Mid-Peak, at RH > 55 %, and at night.
  4. The door-pause restore clamps a utility-offset capture to the 22-25.5 band.

Needs PyYAML + Jinja2 (the Pi's python3 has both; on the Mac use the preflight
venv).  Plain jinja2 is not HA's engine: the stubs cover only what these
templates call, so a green run means "the logic does what the audit asked",
not "HA will accept the file" -- check_config on the Pi remains the gate.
"""
import pathlib
import sys

import jinja2
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


class HALoader(yaml.SafeLoader):
    pass


HALoader.add_multi_constructor('!', lambda loader, suffix, node: None)


def load(path):
    with open(ROOT / path) as fh:
        return yaml.load(fh, Loader=HALoader)


def automation(doc, aid):
    return next(a for a in doc if a.get('id') == aid)


# --- minimal HA template stubs ----------------------------------------------
def ha_env(states, attrs, now_hour=17, isoweekday=2):
    env = jinja2.Environment()

    def f_float(v, default=None):
        try:
            return float(v)
        except (TypeError, ValueError):
            if default is None:
                raise
            return default

    def f_default(v, d='', boolean=False):
        if v is None or (boolean and not v):
            return d
        return v

    env.filters['float'] = f_float
    env.filters['default'] = f_default
    env.filters['bool'] = lambda v: bool(v)
    env.filters['abs'] = abs
    env.filters['max'] = max
    env.filters['min'] = min
    env.filters['string'] = str
    env.filters['round'] = lambda v, p=0, m=None: round(v, p)
    env.globals['is_state'] = lambda e, s: states.get(e) == s
    env.globals['state_attr'] = lambda e, a: attrs.get((e, a))
    env.globals['states'] = lambda e: states.get(e, 'unknown')

    class Now:
        hour = now_hour

        def isoweekday(self):
            return isoweekday

    env.globals['now'] = lambda: Now()
    return env


def render(env, tpl, **ctx):
    out = env.from_string(str(tpl)).render(**ctx).strip()
    # HA parses literal results back into python types; mimic the two we need.
    if out in ('True', 'False'):
        return out == 'True'
    if out == 'None':
        return None
    try:
        return float(out)
    except ValueError:
        return out


def render_vars(env, block, ctx):
    """Render a `variables:` mapping sequentially, like HA does."""
    ctx = dict(ctx)
    for k, v in block.items():
        ctx[k] = render(env, v, **ctx)
    return ctx


# --- 1. evening_comfort_setpoint --------------------------------------------
comfort = automation(load('automations/10_climate_comfort.yaml'), 'evening_comfort_setpoint')
tariff_cond = next(c['value_template'] for c in comfort['conditions']
                   if c.get('condition') == 'template' and 'period_label' in c['value_template'])
for label, expect in (('On-Peak', False), ('Mid-Peak', True), ('Weekend Off-Peak', True), (None, True)):
    env = ha_env({}, {('sensor.grizzl_e_total_cost', 'period_label'): label})
    assert render(env, tariff_cond) is expect, (label, expect)
assert any(t.get('id') == 'evening_late' and t.get('at') == '21:01:00' for t in comfort['triggers'])

# --- 2. advisor trigger -------------------------------------------------------
main = load('automations/01_main.yaml')
adv = automation(main, 'climate_ai_advisor')
assert any(t.get('id') == 'tariff_change' and t.get('attribute') == 'period_label'
           for t in adv['triggers']), 'tariff_change trigger missing'
assert adv.get('mode') == 'queued', 'tariff_change relies on queued mode'

# --- 3. on-peak floor ---------------------------------------------------------
block = next(a['variables'] for a in adv['actions']
             if isinstance(a, dict) and 'variables' in a and 'onpeak_coast' in a['variables'])
# The floor must live in its own block: a second `setpoint:` key in the block that
# first defines it would be a duplicate YAML key and render at the original position.
assert list(block)[0] == 'onpeak_coast', 'on-peak floor block must start at onpeak_coast'
assert 'ai_raw' not in block and 'setpoint' in block and 'setp_apply' in block
base = dict(setpoint_cooldown_ok=False, comfort_correction=False, outdoor_dew_point_c=12.0,
            current_target=23.0, night_mode=False, hvac_mode=None, climate_control_entity='climate.ecobee_3',
            climate_read_entity='climate.ecobee_3', ecobee_compressor_running=True,
            climate_mode_age_minutes=300.0, reason='r')


def scenario(label, rh, setpoint, summer='on', night=False, cooldown_ok=False):
    env = ha_env({'input_boolean.climate_summer_mode': summer, 'climate.ecobee_3': 'cool'},
                 {('sensor.grizzl_e_total_cost', 'period_label'): label})
    ctx = dict(base, humidity_pct=rh, setpoint=setpoint, night_mode=night, setpoint_cooldown_ok=cooldown_ok)
    return render_vars(env, block, ctx)


# Gemini returned null at On-Peak, hold active (the Fri 4 Sep case): floor applies and writes.
r = scenario('On-Peak', 51.0, None)
assert r['onpeak_floor_applied'] is True and r['setpoint'] == 25.5 and r['setp_apply'] is True, r
assert 'on-peak floor' in r['reason']
# Gemini returned 25.5 but the 15:00 write started the hold (Tue 1 Sep): still applies.
r = scenario('On-Peak', 51.0, 25.5)
assert r['onpeak_floor_applied'] is False and r['setp_apply'] is True, r
# Gemini returned 23.0 at On-Peak: floored to 25.5.
r = scenario('On-Peak', 51.0, 23.0)
assert r['setpoint'] == 25.5 and r['setp_apply'] is True, r
# Already at 25.5: no redundant write.
env = ha_env({'input_boolean.climate_summer_mode': 'on'}, {('sensor.grizzl_e_total_cost', 'period_label'): 'On-Peak'})
r = render_vars(env, block, dict(base, humidity_pct=51.0, setpoint=None, current_target=25.5))
assert r['setp_apply'] is False, r
# Humid (RH 58): the floor stays out of it; null stays null.
r = scenario('On-Peak', 58.0, None)
assert r['onpeak_floor_applied'] is False and r['setpoint'] is None and r['setp_apply'] is False, r
# Mid-Peak: untouched, hold still blocks a raise.
r = scenario('Mid-Peak', 51.0, 25.5)
assert r['onpeak_floor_applied'] is False and r['setp_apply'] is False, r
# Winter or night: never.
assert scenario('On-Peak', 51.0, None, summer='off')['onpeak_floor_applied'] is False
assert scenario('On-Peak', 51.0, None, night=True)['onpeak_floor_applied'] is False

# --- 4. door-pause restore clamp ---------------------------------------------
pause = automation(load('automations/06_enhancements.yaml'), 'hvac_pause_door_open')
restore = next(a for a in pause['actions'] if isinstance(a, dict) and 'if' in a
               and 'paused_setpoint' in str(a['if']))
tpl = restore['then'][0]['data']['temperature']
for summer, captured, expect in (('on', 20.8, 22.0), ('on', 23.0, 23.0), ('on', 27.0, 25.5), ('off', 20.8, 20.8)):
    env = ha_env({'input_boolean.climate_summer_mode': summer}, {})
    assert render(env, tpl, paused_setpoint=captured) == expect, (summer, captured, expect)

print('climate TOU guards: OK')
sys.exit(0)
