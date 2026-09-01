# Plan: Kitchen lights on presence during daylight
_Locked via claudex-loop — by Claude + Arshad, 2026-08-31._
_Survived 3 rounds of adversarial review by Codex (gpt-5.6-luna). VERDICT: APPROVED._

## Goal

Walking into the kitchen during the day currently does nothing: `binary_sensor.kitchen_presence
→ on` triggers exactly one automation, and it is gated on `sun.sun == below_horizon`. That
accounts for 104 of 145 walk-ins (72%) over the last 7.6 days.

Make daylight walk-ins bring the cabinet strips up unconditionally, and the main + island
lights up only on genuinely dark days, measured in estimated outdoor lux rather than weather
strings. Unify that "dark day" test with the one `kitchen_light_sync` already applies to the
island light, so the room behaves the same however it was lit.

## Approach

### 1. New tunable — `configuration.yaml`, `input_number:` block

```yaml
  # "Dark day" threshold for the kitchen, in estimated outdoor lux from the
  # ha-illuminance custom integration (sensor.illuminance). Below this, walking
  # into the kitchen in daylight also brings up the main + island lights.
  # Deliberately NOT stairs_dark_lux (1000 lx): across 693 core-daylight samples
  # over 8 days the MINIMUM reading was 10,890 lx, so 1000 would never fire.
  # Overcast days measure 17-20k, partly cloudy 32-41k, clear 74k.
  kitchen_dark_lux:
    name: Kitchen Dark Threshold (lux)
    icon: mdi:brightness-6
    min: 5000
    max: 60000
    step: 1000
    unit_of_measurement: lx
    initial: 20000
```

### 2. New shared sensor — `configuration.yaml`, existing `template: → - binary_sensor:` list

No `device_class` (round 1, finding 3): `device_class: light` would render `on` as
"light detected" while this sensor means the opposite. Attributes expose the inputs so the
flag is debuggable from the UI.

```yaml
      - name: Kitchen Dark Day
        unique_id: kitchen_dark_day
        state: >
          {% set s = states.sensor.illuminance %}
          {% set lux = states('sensor.illuminance') | float(-1) %}
          {% set fresh = s is not none and (now() - s.last_updated).total_seconds() < 3600 %}
          {% if lux >= 0 and fresh %}
            {{ lux < states('input_number.kitchen_dark_lux') | float(20000) }}
          {% else %}
            {{ state_attr('sun.sun','elevation') | float(90) < 5
               or ( state_attr('weather.forecast_home','cloud_coverage') | float(0) > 70
                    and state_attr('sun.sun','elevation') | float(90) < 25 ) }}
          {% endif %}
        attributes:
          lux: "{{ states('sensor.illuminance') }}"
          threshold: "{{ states('input_number.kitchen_dark_lux') }}"
          source_updated: >
            {{ states.sensor.illuminance.last_updated
               if states.sensor.illuminance is not none else 'none' }}
```

The `else` limb runs while `sensor.illuminance` is absent, unavailable, **or stale**, and is
copied from the proven block at `automations/01_main.yaml:3043`.

The 1-hour freshness guard is round 2, finding C. Measured cadence: median update gap 300 s,
but **max observed gap 580 minutes**. Without the guard, a sensor stuck at a low value would
read "dark day" indefinitely and hold the main light on all day — and this repo has already
documented a stuck-at-0 sensor failure mode elsewhere (`reference/climate-setpoint-override.md`).
The guard is safe at night by construction: when it trips, the fallback's `elevation < 5` limb
returns the same "dark" answer the lux test would have.

Two round-3 corrections. First, `now()` makes HA re-render this template every minute, and a
recorded attribute that changes every minute writes a recorder row every minute — an earlier
draft exposed a live `age_s` countdown and claimed rows were written only on a state flip.
That was wrong: attribute changes do create rows (verified in this session — automation entities
churn rows on unchanged attributes, while light `brightness` writes none because it is an
excluded attribute). `age_s` is therefore replaced with `source_updated`, a static timestamp
that moves only when `sensor.illuminance` itself moves (~5-minutely), so churn matches the
source rather than the render clock.

Second, the guard measures **entity update age, not measurement age**. That is a safe proxy
here only because the value is a continuously-varying computation that changes every cycle —
measured: 1,451 rows with no two consecutive identical values, so `last_updated` always tracks
a real recalculation. If ha-illuminance is ever changed to emit a rounded or clamped value, an
unchanged reading would stop advancing `last_updated` and the guard would silently weaken.
Documented failure direction (round 1, finding 9): a missing `cloud_coverage` attribute
defaults to `0`, so the fallback fails toward "not a dark day" — i.e. toward leaving the main
and island lights **off**. That is the safe direction and is intentional.

### 3. Rewrite the `choose` in `kitchen_ambient_restore_on_presence`
`automations/07_presence_sensors.yaml:296`

- Delete the top-level `condition: sun.sun == below_horizon`.
- Update the automation's `description:` — it currently ends "Does nothing while the sun is up",
  which the daylight branch makes false (round 2, finding E).
- Add a top-level kill-switch condition:
  ```yaml
  - condition: state
    entity_id: input_boolean.kitchen_auto_lights_disable
    state: "off"
  ```
- Cancel any in-flight fade before restoring (round 1, finding 5) — first action, before the
  existing `adaptive_lighting.set_manual_control` release:
  ```yaml
  - action: script.turn_off
    target:
      entity_id: script.kitchen_lights_step_dim
  ```
- Replace the two-branch `choose` with **three explicitly-gated branches and no bare
  `default:`** (round 1, finding 2 — this is the critical fix):

  | order | branch | gate | action |
  |---|---|---|---|
  | 1 | daylight | `sun.sun == above_horizon` | 5 strips @100%; **if** `binary_sensor.kitchen_dark_day == 'on'` also main + island @100% |
  | 2 | overnight | `sun.sun == below_horizon` **and** `bedtime_shutdown_done == 'on'` **and** time 21:00–09:00 | 5 strips @50% (unchanged) |
  | 3 | evening | `sun.sun == below_horizon` | all 7 @100% (unchanged behaviour, now explicitly gated) |

  Removing the bare `default:` is the point: previously the top-level sun condition made an
  `unknown`/`unavailable` `sun.sun` a no-op. Without that condition a bare default would turn
  all seven lights on at full brightness during any sun-integration hiccup. All three branches
  now require a real `sun.sun` state, so unknown is a deliberate no-op.

  Daylight must be branch 1: the overnight branch's `21:00–09:00` window overlaps summer
  daylight, and its own comment says the sun condition — not the 09:00 bound — is what ended
  that window at sunrise.

- Every `light.turn_on` gets `continue_on_error: true` (round 1, finding 8), and the strips and
  the main+island group stay in **separate** calls so one unavailable entity cannot abort the
  other group. Directly motivated by the 17.9 h `light.kitchen_light_light_1` outage on 08-30.

### 4. Harden the dimming tail — `automations/07_presence_sensors.yaml:270`

Round 1, finding 6. The post-delay re-check is a bare state test, so a presence bounce during
the 2-minute delay still satisfies it and the lights go off seconds after someone re-enters:

```yaml
  - if:
    - condition: state
      entity_id: binary_sensor.kitchen_presence
      state: "off"
      for: "00:02:00"        # <- added; was a bare state check
```

### 5. Unify the island test — `automations/02_kitchen_light_sync.yaml:57`

Replace the `weather.forecast_home in [cloudy, overcast, partlycloudy, rainy, snowy, fog]
OR uv_index < 4` block with:

```yaml
                - condition: state
                  entity_id: binary_sensor.kitchen_dark_day
                  state: "on"
```

Keep the existing pre-sunrise `not` guard untouched.

### 6. Verify

`verification/preflight.sh`, then on the Pi
`docker exec homeassistant python -m homeassistant --script check_config --config /config`.
Only after that passes: reload, then `verification/smoke-tests.sh`. Both the deploy and the
reload need explicit user approval per CLAUDE.md.

Three additional post-deploy checks (round 2):

- **`script.turn_off` must stop *all* parallel runs**, not just one, or the cancellation in
  step 3 is decorative. Verify: start `script.kitchen_lights_step_dim` twice with a long ladder,
  call `script.turn_off`, confirm both runs stop and no further `light.turn_on` calls appear in
  the logbook.
- **`binary_sensor.kitchen_dark_day` renders on both limbs.** Verify by temporarily setting
  `input_number.kitchen_dark_lux` above and below the current `sensor.illuminance` reading and
  watching the state flip; check the `source_updated` attribute is populated.
- **The daylight branch wins over the overnight branch.** Verify with a walk-in between sunrise
  and 09:00 while `input_boolean.bedtime_shutdown_done` is still `on` — expect the daylight
  treatment (strips at 100%), not the overnight 50%.

## Key decisions & tradeoffs

- **20000 lx, on a new knob** (Q1). Reusing `stairs_dark_lux` (1000 lx) would have shipped a
  feature that never fires: the minimum core-daylight reading across 693 samples over 8 days
  was 10,890 lx. Daily medians separate cleanly — overcast 17–20k, partly cloudy 32–41k,
  clear 74k.
- **One automation stays the sole owner** (Q2). `07_presence_sensors.yaml:201` declares
  "Single owner for all seven kitchen lights"; the repo documents two prior incidents from
  split ownership (the `kitchen_light_sync` flicker feedback loop, and the mmWave radar driving
  kitchen lights from a bedroom).
- **One shared dark-day definition** (Q3). The weather/UV and lux tests disagree on **40% of
  core-daylight samples (280/693)**, always in the same direction — the weather test calling
  `partlycloudy` at 44,475 lx "dark". Accepted behaviour change: the island light will stop
  coming on during bright partly-cloudy days when the wall switch is flipped.
- **Kill switch is turn-on only.** `input_boolean.kitchen_auto_lights_disable` gates presence-
  driven turn-**on**. Dimming and sync are deliberately outside it — a kill switch should not
  also prevent lights turning off.
- **Edge-triggered only.** No re-evaluation if cloud cover changes while someone is standing in
  the kitchen.
- **No new OFF path.** `kitchen_ambient_graduated_dimming` has no sun condition and is already
  proven in daylight — 39 daylight fires, strips went `on → off` in 11 of 12 sampled cases.

## Assumptions

1. `binary_sensor.kitchen_presence` is the sole presence source; the `*kitchen_mmwave*`
   entities are master-bedroom hardware and drive nothing.
   — source: `configuration.yaml:855`, project memory `kitchen-presence-ownership`
2. `sensor.illuminance` (ha-illuminance: solar position × cloud cover) is a *computed*
   estimate, not a photodiode. 8 unavailable rows in 1,451 over 7.6 days.
   — source: recorder query; `configuration.yaml:70`
3. Both AL groups are configured `min_brightness: 100, max_brightness: 100`, so AL pins these
   strips at 100% and `brightness_pct: 100` will not fight it.
   — source: `.storage/core.config_entries`, "Cabinet Strips" / "Cabinet Kick Plate"
4. Turning the main light on from this automation will NOT re-trigger `kitchen_light_sync`:
   its `trigger.to_state.context.parent_id is none` condition suppresses automation-driven
   changes. — source: `automations/02_kitchen_light_sync.yaml:24`
5. HA restart needs no reconciliation automation: `input_boolean.kitchen_tuya_presence` has
   `initial: false`, and `tuya_kitchen_bridge.py` re-pushes true state within
   `REPUSH_INTERVAL = 60` s, producing a genuine off→on edge. **Verified** (round 2, finding A):
   `tuya-kitchen-bridge.service` (`Restart=always`, `Requires=docker.service`) has been
   continuously active since 08-27 20:35:46, spanning the HA restarts at 08-28 00:32 and 00:33,
   and 140 presence state rows were recorded after them. A second path exists as a belt-and-
   braces: the `tuya_kitchen_bridge_startup` automation runs
   `shell_command.start_tuya_kitchen_bridge` on every HA start.
   — source: `tuya_kitchen_bridge.py:36,139`; `systemctl status`; `recorder_runs` query
   — caveat: that systemd unit is **not tracked in git** (`pi-config/` does not carry it), so
   this guarantee is host state, not repo state.
6. Root `automations.yaml` is legacy and not loaded. — source: `CLAUDE.md`
7. Deploying or reloading anything on the Pi requires explicit user approval.
   — source: `CLAUDE.md`

## Risks / open questions

- **Seasonal drift — the main unresolved risk, and a logged cross-model disagreement.**
  20000 lx is calibrated on 8 days of late-August data. In midwinter, clear-sky noon at this
  latitude is far below summer levels and may sit under the threshold all day, turning the main
  light on continuously.

  *Codex's position (raised round 1, held round 2):* an absolute lux threshold is not
  season-stable; either require seasonal calibration before deploying, or derive the threshold
  from a normalized cloud/solar value.

  *Claude's position:* absolute lux is the **correct semantic** here. The question the user
  asked is "is it dark enough that I want the lights on", and a dark December noon genuinely is
  darker than a bright August noon — firing then is arguably right, not a bug. Normalizing
  against clear-sky would instead encode "is it cloudy for this time of year", which is the
  question the weather/UV test already answered badly. Blocking deployment until winter means
  shipping nothing for four months. Hysteresis is moot: the automation is edge-triggered on
  presence and reads a 5-minutely sensor, so there is no loop to oscillate.

  *Unresolved, and deliberately so.* The mitigation is that the correction costs **one slider
  move, no code change** — `input_number.kitchen_dark_lux` is exposed, and the sensor publishes
  `lux`, `threshold` and `age_s` attributes so the reason for any decision is visible. Concrete
  review checkpoint: the first heavy-overcast day after the autumn equinox, compare
  `sensor.illuminance` daytime medians against 20000 and re-tune. **This is the one item where
  the two models did not converge; the user should decide whether that is acceptable.**
- `sensor.illuminance` updates roughly every 5 minutes, so the flag lags a fast cloud front.
- Unresolved, out of scope: localtuya/`tuya_kitchen_bridge.py` dual ownership of 192.168.0.61,
  and the 17.9 h `light.kitchen_light_light_1` outage on 08-30.

## Out of scope

- The daytime OFF path (already works).
- Fixing the main light's localtuya dropout, and the Tuya bridge/localtuya contention.
- Any change to the overnight or evening branches' lighting behaviour.
- `input_boolean.kitchen_occupied_motion` (still dead; left alone).
