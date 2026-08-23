# The Ecobee runs a different setpoint than the one we write

**Incident 2026-08-22.** The house sat warm all day while `climate_ai_advisor`
reported success on every run. The compressor did not fire once in 15.5 h
(11:18 → 03:00 UTC) while indoor drifted 21.4 °C → 24.0 °C.

Nothing in this repo was broken.

## What actually happened

The thermostat carries a utility **`touSetback`** event. As captured live on
2026-08-22 (a **Saturday**):

```python
{'type': 'touSetback', 'name': 'sbk070000',
 'startDate': '2026-08-22', 'startTime': '07:00:00',
 'endDate':   '2026-08-22', 'endTime':   '23:00:00',
 'isTemperatureRelative': True,
 'coolRelativeTemp': 20,          # 0.1 °F units -> +2.0 °F -> +1.11 °C
 'heatRelativeTemp': 40,
 'isOptional': True,
 'linkRef': '020fee13880006473857'}   # utility-linked
```

`coolRelativeTemp: 20` is added to **every cooling setpoint**, invisibly.
Climate AI wrote 23.0 °C; the equipment ran 24.1 °C; the room was 23.9 °C.
Idle was the *correct* behaviour — the target was simply never reachable.

+2.0 °F sits inside ecobee's documented 1–4 °F Community Energy Savings
adjustment range, so this is near-certainly IESO **Peak Perks** (or Hydro One
myEnergy Rewards) via ecobee eco+.

### The schedule is event-driven, not a fixed weekday rule

Do not assume "weekdays 07:00–23:00" from the single payload above. Measuring
the exact +1.11 °C signature across 8 days of history gives a different and
much less regular picture (local time):

| Day | +1.11 °C active | Samples |
| --- | --- | --- |
| Sun 08-16 | 15:03 → 22:54 | 60 |
| Mon 08-17 | 19:04 → 20:57 | 24 |
| Tue 08-18 | *(none)* | 0 |
| Wed 08-19 | 19:04 → 20:54 | 16 |
| Thu 08-20 | 19:26 → 20:59 | 16 |
| Fri 08-21 | 19:04 → 20:46 | 28 |
| **Sat 08-22** | **09:06 → 22:58** | **79** |

A typical day is a ~2 h evening event around 19:00–21:00. Weekends can run far
longer, and 08-22 was an outlier at ~14 h — which is why that day, and not the
others, produced a visibly warm house. Compressor duty that day was the second
lowest of the week (3.8 h / 15.6 %) despite it being warm.

The offset is dispatched by the utility per event, so **predict nothing from
the calendar** — read the live `touSetback` event or the divergence sensor.

### Distinguishing a real override from sync lag

Over 8 days, 223 of 248 override samples were **exactly +1.1 °C**. The
remainder (+0.9, +1.2, +1.4, +1.5, +2.1, +2.5, +3.0) were one-offs clustered at
`:00` write boundaries, i.e. HA had written a new setpoint and the HomeKit
bridge had not caught up yet.

So: a *persistent* +1.11 °C is the utility program; a *single sample* of some
other size right after a setpoint write is almost certainly harmless lag. The
≥0.5 °C alert threshold catches both, which is intentional — the advisor only
evaluates it right after its own write, and a sustained lag is worth seeing.

## Proof

The setback expired at 23:00:14 local while the incident was being
investigated. No config changed; the compressor started within seconds:

```
02:59:48  cloud_tgt 23.0  cur 23.8 | eq ''              act idle
03:00:18  cloud_tgt 22.0  cur 23.9 | eq 'compCool1,fan' act cooling
```

## Why every self-check missed it

`climate_ai_advisor` verified a write by reading back the **same cloud
attribute it had just written**, so `23.0 == 23.0` passed and
`setpoint_persisted` was true. The retry-through-SmartThings path and the
"did not persist" notification could never fire.

The two HA entities disagree by design, and that disagreement is the *only*
local signal that an override exists:

| Entity | Integration | Reports |
| --- | --- | --- |
| `climate.ecobee_3` | `ecobee` (cloud API) | the setpoint we **requested** |
| `climate.ecobee`   | `homekit_controller` | the setpoint actually **running** |

## What was added (2026-08-22)

- `sensor.climate_ai_setpoint_divergence` — effective minus requested, with an
  `overridden` attribute at the ≥0.5 °C threshold.
- An advisor notification when the override is ≥0.5 °C, kept **separate** from
  the did-not-persist alert because the remedy is different: this one is fixed
  on the utility/thermostat side, not by retrying a write.
- An `EXTERNAL SETPOINT OVERRIDE` block in the Gemini prompt, so the model
  targets the *effective* setpoint and prefers fans/vent boosters instead of
  stacking setpoint drops it cannot win.

Both detection paths fail safe. `climate.ecobee` dropped its `temperature`
attribute 4 times in 7 days; on those the divergence sensor goes
*unavailable* and the alert stays silent rather than raising a false alarm.

## How to live with it (decision: the program is being KEPT)

⚠️ **Do not "fix" this by unenrolling.** The enrollment is deliberate: it pays
**$75 up front plus $20/season**. The override is the price of that money, not a
bug, and the automation is written to cooperate with it rather than fight it.

If someone ever does want out, note it is not an in-app toggle — per ecobee
support you must contact the *program provider* (Alectra, or IESO Save on
Energy for Peak Perks) and ask them to remove the thermostat. Disabling eco+
also drops Community Energy Savings. Neither should be done casually; both
forfeit the incentive.

**Per-event escape hatch.** Events carry `isOptional: True`, so a single event
can be cancelled without leaving the program: set a Hold on the thermostat, or
tap the arrow beside "eco+ is on" and end eco+ for the day. It returns
tomorrow. Use this on the rare long event, not routinely.

### The strategy that actually works: buffer, don't fight

A +1.11 °C hold is only uncomfortable if the house enters the event sitting
*exactly* at target. Pre-cooled, it coasts straight through.

1. **Pre-cool 17:00–19:00** whenever the tariff is Ultra-Low or Off-Peak and
   rooms are occupied. Events historically start near 19:00, so this is where
   thermal buffer is cheapest to build. This also aligns with the existing ULO
   strategy rather than competing with it.
2. **During an event, use air movement.** Ceiling fans and vent boosters
   restore perceived comfort without fighting the hold, and cost far less than
   the compressor.
3. **Compensate the request, within limits.** The advisor may subtract the
   override so the *effective* target lands where intended, but only down to
   the 22.0 °C floor and only when an occupied room is genuinely above the
   effective target. Stacking large drops just to out-muscle the hold is
   explicitly discouraged.

The advisor prompt encodes all three, and the notification is deliberately
informational: it fires only when an override is active **and** indoor is more
than 0.5 °C above the effective target, i.e. when the buffer actually failed.
A normal, well-buffered event stays silent.

## Second failure found while investigating

`sensor.ecobee_current_temperature` (HomeKit) latched to exactly **0** at
2026-08-20T18:54 and was still 0 three days later. It never went
`unknown`/`unavailable`, so every presence-only template happily forwarded 0 as
the house temperature.

That silently disarmed `climate_safety_backstop`: its `above: 4` dropout guard
means a stuck 0 can never fire the freeze branch, and 0 is never above 27, so
the overheat branch died too. **The last line of defence was dead for 2.5
days.**

Fixes: the backstop and the other live consumers now read the canonical
`sensor.climate_ai_ecobee_temperature`, and every `climate_ai_*` temperature
sensor now requires each candidate to be **present *and* plausible**
(`4 < t < 45`), normalising to °C *before* the test.

### Trap: the raw sensor suffixes are inconsistent per room

Native ecobee is `_3` where three feeds exist and `_2` where two do. Confirmed
against the cloud `remoteSensors` payload:

| Room | native ecobee | homekit | smartthings |
| --- | --- | --- | --- |
| Ecobee (main) | `ecobee_temperature_2` | `ecobee_current_temperature` ⚠️ dead | `ecobee_temperature` |
| Master Bedroom | `master_bedroom_temperature_2` | `332d_temperature` | `master_bedroom_temperature` |
| Guest Room | `guest_room_temperature_2` | `bbwg_temperature` | `guest_room_temperature` |
| Minas Room | `minas_room_temperature_3` | `minas_room_temperature` | `minas_room_temperature_2` |
| Izaans Room | `izaans_room_temperature_3` | `izaans_room_temperature` | `izaans_room_temperature_2` |
| Basement | `basement_temperature_3` | `basement_temperature` | `basement_temperature_2` |

Sensor codes: `332D` Master, `BBWG` Guest, `PKST` Basement, `PKT3` Izaan,
`XYFT` Mina.

Do not "normalise" these names — the suffixes are assigned by HA in discovery
order and renaming churns entity IDs for no functional gain.

## Diagnosing a recurrence

```bash
# Requested vs effective, plus what the equipment is doing
python3 - <<'PY'
import json,urllib.request,os
tok=[l.split('=',1)[1].strip().strip('\'"') for l in
     open(os.path.expanduser('~/.hermes/.env')) if l.startswith('HASS_TOKEN=')][0]
h={'Authorization':f'Bearer {tok}'}
st={s['entity_id']:s for s in json.load(urllib.request.urlopen(
    urllib.request.Request('http://localhost:8123/api/states',headers=h)))}
c=st['climate.ecobee_3']['attributes']; k=st['climate.ecobee']['attributes']
print('requested',c['temperature'],'effective',k['temperature'],
      'indoor',c['current_temperature'],'equip',repr(c['equipment_running']))
PY
```

To see the raw event list, enable `pyecobee` debug, force an update, then grep
the response for `'events':`:

```bash
# logger.set_level pyecobee: debug   ->  homeassistant.update_entity climate.ecobee_3
docker logs homeassistant --since 60s 2>&1 | grep 'Request response' | tail -1
```

`equipment_running: ''` while indoor sits above the *requested* target is the
signature. Compare against the effective target before suspecting this repo.
