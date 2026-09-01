# Why the kitchen automation doesn't fire every time you walk in

_claudex-loop Phase 0 recon. Evidence: the Pi's recorder DB, read-only, full retained
history **08-24 06:29 → 08-31 21:55 EDT (7.6 days)**. No changes made to the Pi._

## Answer in one line

The automation is not unreliable — **after dark it fired 40 out of 41 times**. It feels
random because **72% of your walk-ins happen in daylight, where nothing is designed to
fire at all**, and one Saturday the main kitchen light was offline for 18 hours.

| | walk-ins | restore automation fired |
|---|---|---|
| daylight | 104 (72%) | **0** — blocked by `sun.sun == below_horizon`, by design |
| after dark | 41 (28%) | **40 / 41 (98%)** |
| | **145 total** | |

The one night miss (08-27 20:33:17) landed inside a cluster of HA restarts
(recorder runs 19:52→23:12 that evening) — a startup artifact, not a missed walk-in.
Effectively the trigger is 100% after dark.

**Net: 113 of 145 walk-ins (78%) could produce no visible response** — 104 daylight
+ 9 where the main light was unavailable.

## Method / instrument note

The first two passes read automation `last_triggered` out of `state_attributes`. That is
**not recorded** — HA stores only `friendly_name` for automation entities — so both the
"never fires" and "always fires" readings taken from it were meaningless. Every number
above comes from the authoritative `automation_triggered` and `call_service` event tables.
`brightness` is likewise excluded from the recorder by HA's `light` integration, so dim
ladders can't be reconstructed; only on / off / unavailable transitions are visible.

## Cause 1 — daylight is a no-op by design (72% of walk-ins)

`binary_sensor.kitchen_presence` → `to: "on"` is a trigger in **exactly one** loaded
automation: `kitchen_ambient_restore_on_presence`
([automations/07_presence_sensors.yaml:305](automations/07_presence_sensors.yaml:305)),
and it carries `condition: sun.sun == below_horizon`.

Nothing else responds to presence starting:

- `kitchen_light_sync` triggers on the **main light** changing, not presence
- `kitchen_main_light_presence_guard` triggers on the light going **off**
- `kitchen_ambient_graduated_dimming` triggers on presence **ending**

So walking into the kitchen in daylight has never turned a light on, and never will
without a config change. This is the single biggest contributor to "it feels random".

## Cause 2 — the main kitchen light went offline for 18 hours (one event, not chronic)

`light.kitchen_light_light_1` (localtuya) over the full 7.6 days:

- **18.7 h unavailable of 183.4 h = 10.2%**
- outages >10 min: **only three**
  - **08-30 05:20 → 08-30 23:16 — 17.9 h** (essentially all of it)
  - 08-31 02:00 → 02:10 (0.2 h)
  - 08-31 07:59 → 08:23 (0.4 h)

While unavailable, `light.turn_on` is a silent no-op — the automation fires, HA issues the
call, nothing lights up. This hit **9 of the 41** night walk-ins, all on 08-30 evening.

> Correction to my first pass: I initially reported 25.9%, measured over a 3-day window
> that happened to be dominated by this one outage. Over the full retention it is 10.2%
> and concentrated in a single day. This is **one bad Saturday, not a chronic dropout** —
> worth noting, not worth chasing as a standing network problem unless it recurs.

`light.island_light_light` on the same integration was only 1.3% unavailable, so the
outage was specific to that device rather than a blanket localtuya failure.

## Cause 3 — three cabinet-strip misses, same bad evening

Of 47 lights that were off at a restore fire, 10 failed to come on within 60 s. Seven are
the unavailable main light. The other three are the cabinet strips at 20:43 / 21:06 /
21:13 on 08-30 — inside the same outage evening.

Tested whether adaptive lighting explained it: at those three misses **and** at three
neighbouring fires that worked, `switch.cabinet_strips_adaptive_lighting_cabinet_strips`
was `on` and the strips were `off` in all six cases. AL is not the discriminator. Filed as
transport flakiness clustered in one evening, not a separate config defect.

## Robustness note — two clients own the Tuya presence sensor

`192.168.0.61` is polled by `tuya_kitchen_bridge.py` (tinytuya, every 2 s) **and** owned by
a localtuya config entry (verified in `.storage/core.config_entries`: entry
`localtuya / z1cooumg@arshad14.anonaddy.me`). Tuya 3.5 allows one local session, so the two
collide — correlated in the logs:

```
08-30 13:08–13:11   bridge "Check device key or version" x12  ↔  localtuya handshake fail x4
08-31 13:24         bridge x3                                  ↔  localtuya handshake fail x1
08-31 20:00         bridge x1                                  ↔  localtuya handshake fail x4
```

Cost in the observed window: 19 failed polls and 10 handshake failures over 7.6 days, and
**zero dropped presence edges**. Real and worth cleaning up eventually; **not** a cause of
the reported symptom.

## Ruled out (tested, negative — not assumed)

- **Dimming killing the lights after you walk in.** Zero kitchen lights went ON→OFF within
  180 s of any night walk-in. The `delay: "00:02:00"` re-check race in
  `kitchen_ambient_graduated_dimming` never fired.
- **`script.kitchen_lights_step_dim` overwriting a restore.** `mode: parallel` makes it
  possible; zero occurrences in the window.
- **Presence sensor dropping out.** 0.0% unavailable for both
  `binary_sensor.kitchen_presence` and `input_boolean.kitchen_tuya_presence`.
- **Automations disabled.** All four kitchen automations are `on`.

## Incidental findings

- `input_boolean.kitchen_auto_lights_disable` and `input_boolean.kitchen_occupied_motion`
  are declared in configuration.yaml and **referenced by nothing**. The disable toggle
  does not disable anything.
- One `script.kitchen_lights_step_dim` crash, 08-31 12:53:14:
  `'NoneType' object has no attribute 'request'`. Single occurrence.
