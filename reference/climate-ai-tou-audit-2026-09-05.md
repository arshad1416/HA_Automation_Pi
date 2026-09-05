# Climate AI / time-of-use audit — 2026-09-05

**Question asked:** is `climate_ai_advisor` drifting and running the condenser
without regard to the ULO tariff, and is that why usage "shot up" over the
last couple of months?

**Short answer:** No to the premise, yes to four smaller defects.

- Grid import in July and August 2026 was **lower** than the same months in
  2025 (−9 % and −13 %), on-peak import roughly **halved**, and the
  weekday on-peak window is now a **net exporter** (solar). The rise the
  bills show is seasonal (May → July every year), the 1 Nov 2025 OEB rate
  increase (+29–39 % on every ULO tier), and ~1,100 kWh/month of EV charging
  since the VF9 arrived at the end of July — almost all of it at 3.9 ¢.
- The advisor does have four concrete TOU/setpoint defects, all visible in
  the last recorder week (28 Aug – 4 Sep). None of them is large in dollars,
  but each is a one-line fix. See §4.

Data sources: My Alectra portal (billing months, hourly import and export
with tier), Open-Meteo daily temperatures for Waterdown, the Pi recorder
(7-day window only — `purge_keep_days: 7`), long-term statistics for the
Grizzl-E charger, and the repo. Method notes and caveats are in §6.

---

## 1. Usage did not go up year over year

Billing periods (Alectra "consumption" channel = grid import, net of solar
behind the meter):

| Bill period | Import kWh | kWh/day | Energy $ | Export kWh | Credit $ |
| --- | ---: | ---: | ---: | ---: | ---: |
| 28 May – 26 Jun 2025 | 1,981 | 68.3 | 136.89 | 873 | 114.24 |
| 26 Jun – 28 Jul 2025 | 2,642 | 82.6 | 166.08 | 1,036 | 133.39 |
| 28 Jul – 28 Aug 2025 | 2,559 | 82.6 | 155.81 | 784 | 104.64 |
| 28 May – 25 Jun 2026 | 1,491 | 53.3 | 119.64 | 902 | 168.22 |
| 25 Jun – 28 Jul 2026 | 2,406 | 72.9 | 197.56 | 881 | 159.99 |
| 28 Jul – 28 Aug 2026 | 2,223 | 71.7 | 167.47 | 878 | 166.56 |

The "shot up" is the May → July step. It happens every year (2025: 960 →
1,981 → 2,642). The dollar figures rose because every ULO tier was re-priced
on 1 Nov 2025 (overnight 2.8 → 3.9 ¢, weekend 7.6 → 9.8 ¢, mid-peak
12.2 → 15.7 ¢, on-peak 28.4 → 39.1 ¢). The export credit rose with it
(13 ¢ → 18–19 ¢/kWh), so **net energy cost this summer is flat to lower**:
July $38 vs $33, August $1 vs $51.

## 2. Where the kWh go, by tariff tier (calendar months, hourly data)

| Month | Import | Ultra-Low | Weekend | Mid-Peak | On-Peak | On-peak $ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Jul 2025 | 2,590 | 1,779 (69 %) | 316 | 315 | 180 (6.9 %) | 51.01 |
| Aug 2025 | 2,308 | 1,556 (67 %) | 341 | 277 | 135 (5.8 %) | 38.31 |
| Jul 2026 | 2,175 | 1,398 (64 %) | 353 | 306 | 118 (5.4 %) | 46.11 |
| Aug 2026 | 2,311 | 1,654 (72 %) | 318 | 268 | 71 (3.1 %) | 27.72 |

Weekday on-peak hours (16:00–20:59), July + August combined:

| Year | Import | Export | Net |
| --- | ---: | ---: | ---: |
| 2025 | 329 kWh | 267 kWh | +62 kWh imported |
| 2026 | 206 kWh | 310 kWh | −105 kWh exported |

Two things follow. First, the TOU shape got *better*, not worse. Second,
because the house is net-metered, **daytime AC is invisible in the import
channel** — weekday import between 09:00 and 17:00 averages 0.1–0.6 kWh/h
even on 30 °C days. The real cost of afternoon cooling is forgone export
credit at the tier rate (15.7 ¢ mid-peak, 39.1 ¢ on-peak), which is why the
export channel is the one to watch for on-peak AC, not the import channel.

## 3. Weather and the other loads

| Month | Mean T | CDD₁₈ | Days ≥ 30 °C | Import kWh | kWh per CDD |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jul 2025 | 23.7 °C | 176 | 14 | 2,590 | 14.7 |
| Aug 2025 | 20.9 °C | 105 | 5 | 2,308 | 21.9 |
| Jul 2026 | 22.5 °C | 140 | 6 | 2,175 | 15.6 |
| Aug 2026 | 20.6 °C | 83 | 0 | 2,311 | 27.8 |

Daily import regressed on daily mean temperature (Jul + Aug):

- 2025: 5.7 + **3.29** kWh/day per °C
- 2026: 44.1 + **1.31** kWh/day per °C

The house's import is far *less* temperature-sensitive in 2026 and has a much
larger flat component. That flat component is the EV load:

- **Grizzl-E, Aug 2026: 1,097 kWh** — 938 ULO (85 %), 105 weekend, 44
  mid-peak, 10 on-peak. Charging every day, peak day 82 kWh. The VF9's first
  charges appear 30 Jul; August is the first full month with two EVs.
- Night-time regression (23 hours, 28–31 Aug, solar = 0, EV subtracted):
  `import = 1.39 + 2.68 × compressor_on + 0.93 × pool_pump_on` kW, R² 0.60.
  So the condenser draws ~2.7 kW while running, the pool pump + chlorinator
  socket ~0.9 kW, and the base (dehumidifier, network, fridge, standby) is
  ~1.4 kW.
- The pool pump socket was on 130 of 172 hours in the recorder week (off
  only 16:00–21:00 weekdays). At 0.9 kW that is ~600 kWh/month, more than
  the condenser's overnight share. It has no power monitoring, so this is
  the regression estimate, not a measurement.

Compressor minutes per day in the recorder week, by tier (run / available):

| Day | Mid-Peak | On-Peak | Ultra-Low / Weekend |
| --- | ---: | ---: | ---: |
| Fri 28 Aug | 72 / 660 | 3 / 300 | 98 / 226 |
| Sat 29 Aug | — | — | 146 ULO, 17 wknd |
| Sun 30 Aug | — | — | 317 ULO, 0 wknd |
| Mon 31 Aug | 102 / 660 | 0 / 300 | 299 / 480 |
| Tue 1 Sep | 335 / 660 | 91 / 300 | 248 / 480 |
| Wed 2 Sep | 248 / 660 | 66 / 300 | 53 / 480 |
| Thu 3 Sep | 291 / 660 | 53 / 300 | 238 / 480 |
| Fri 4 Sep | 126 / 660 | 117 / 300 | 194 / 473 |

## 4. Defects found in the advisor and its neighbours

All four are visible in the recorder week; none is a hypothesis.

### 4.1 `evening_comfort_setpoint` writes 23 °C into weekday on-peak

`automations/10_climate_comfort.yaml` triggers on the Ecobee *Evening*
profile transition (19:00) with no tariff condition, and re-asserts
22.5–23.5 °C over whatever the advisor set. On weekdays 19:00 is On-Peak
(39.1 ¢). It fired at 19:00 every weekday of the window and again at
20:00/20:01 on Tue and Wed, because the thermostat re-enters *Evening*
whenever the utility hold releases.

- Tue 1 Sep: advisor coasted to 25.5 °C at 17:00; 19:00 → 23.0, 20:01 →
  23.0 again. The utility's +2.5 °C setback happened to hold the effective
  target at 25.5 / 24.1, so no compressor time was lost.
- Fri 4 Sep: no utility event. 19:00 → 23.0, effective 23.0, compressor
  started immediately; **117 min of on-peak cooling** that day, 30 of them
  in the 20:00 hour.

The utility Peak Perks setback is what has been protecting on-peak, not this
repo. Fix: add a condition that the live period label is not On-Peak (or
`now().isoweekday() > 5 or not (16 <= now().hour < 21)`), and let the 21:00
mid-peak run or the 23:00 Sleep transition set the ladder instead.

### 4.2 The 16:00 advisor run reads the *old* tariff

The advisor triggers on `time_pattern minutes: 0`, i.e. 16:00:00. The
Grizzl-E daemon flips `period_label` to On-Peak 3–14 s later every day
(16:00:03 … 16:00:14 in the window). The prompt tells Gemini the live label
is "authoritative for the current decision", so the 16:00 decision is made
as a Mid-Peak decision. Every 16:00 reason string in the window is
tariff-silent ("close to the 23.0 baseline, no change"), every 17:00 one
says "On-peak, coast to 25.5". Result: **53–60 compressor minutes in the
16:00 hour** on Tue/Wed/Thu at 39.1 ¢ (≈ 2.5 kWh/day ≈ $1/day energy, plus
forgone export while the sun is still up).

Fix (pick one): add a state trigger on
`sensor.grizzl_e_total_cost` attribute `period_label` so the run fires when
the tariff actually changes, or compute the period in the prompt from
`now()` and the rules in `grizzl_e_rates.json` instead of the daemon
attribute.

### 4.3 Coasting is prompt-only, so it is inconsistent

The only on-peak logic is prose in the prompt, and even when Gemini follows
it the write is usually blocked. The recommendation log marks an applied
setpoint with `*`. In the window:

- Tue 1 Sep 17:00 `set=25.5` (no `*`), Wed 2 Sep 17:00 `set=24.5` (no `*`):
  proposed, **not applied**. The 15:00 "baseline" write had started the
  two-hour setpoint hold (`setpoint_cooldown_ok` false) and
  `comfort_correction` only exempts *decreases*, so a raise at 17:00 is
  always blocked whenever the advisor wrote at 15:00. The 25.2–25.5 °C the
  thermostat showed at 17:00 on those days was the utility's +3.3 °C
  setback (divergence sensor), not this repo.
- Thu 3 Sep 16:54 `set=25.5*`: applied, only because the last write was the
  previous day.
- Fri 4 Sep: never proposed ("within 0.5 °C of the 23.0 target; no change
  needed") — the hysteresis instruction beat the tariff instruction.
- Mon 31 Aug: handled by the utility (25.5 at 16:00, preset `home`).

So across five weekdays the advisor itself coasted once. The deterministic
`climate_peak_protect` that used to do this is fenced to
`climate_ai_enabled == off`, so nothing enforces it. (Credit: the
blocked-write reading came from Codex's parallel audit; my first pass
mis-read the 17:00 proposals as applied.)

Fix: enforce it in the automation, not the prompt. In the `setp_apply`
variables, when summer mode is on, the period is On-Peak and indoor RH ≤
55 %, floor the applied setpoint at 25.0/25.5 regardless of what Gemini
returned, and exempt an on-peak *increase* from the two-hour hold the same
way `comfort_correction` exempts an urgent decrease. Alternatively un-fence
`climate_peak_protect` and let the advisor's hold respect it.

### 4.4 `hvac_pause_door_open` round-trips the utility offset

`automations/06_enhancements.yaml` captures `paused_setpoint` from
`climate.ecobee_3` before pausing and writes it back on restore. During the
utility's 14:00–16:00 pre-cool the cloud entity already reports the
offset-applied value (23.0 − 2.2 = 20.8 °C). Thu 3 Sep: paused 14:47 with
20.8 captured, restored 15:20 → requested 20.8, and the utility subtracted
its −2.2 °C again → **effective target 18.6 °C** (HomeKit
`climate.ecobee`), indoor 24.3 °C. The 15:59 pause/restore did it a third
time (21.9 → 20.8).

Fix: clamp the restored value to the advisor's band, e.g.
`{{ [[paused_setpoint | float(23), 22.0] | max, 25.5] | min }}` in summer
mode, or skip the restore write entirely when `climate_ai_enabled` is on and
let the next hourly run settle it.

### Observations that are policy, not bugs

- **21:00–23:00 re-cool at mid-peak.** When on-peak ends the effective
  target snaps back to 23.0 (from 4.1 above) and the compressor runs
  39–54 min in the 21:00 hour and up to 60 in the 22:00 hour every day,
  at 15.7 ¢ — two hours before the 3.9 ¢ window. Holding 24.5 until 23:00
  and letting the Sleep 22.0 write do the work would move ~4 kWh/day from
  15.7 ¢ to 3.9 ¢ (≈ $14/month). Comfort trade-off; the user's call.
- **Mid-morning pull-down.** The thermostat's own schedule sets 24.4 °C
  (weekdays) / 25.5 °C (weekends) at 07:00 (`preset: home`, i.e. eco+ or the
  comfort profile, not a hold). The advisor "normalises to the 23.0
  baseline" at 09:00–12:00 every day. The comfort ladder is tariff-blind by
  design; with net metering the marginal cost of that daytime cooling is
  the lost mid-peak export credit (15.7 ¢), roughly 200 compressor min/day
  ≈ 9 kWh ≈ $1.40/day. Again a preference, but worth knowing the price.
- **Utility pre-cools are doing real work.** 05:00–06:00 to 19.8 °C (ULO)
  and 14:00–16:00 to 20.8 °C (mid-peak) precede the +1.1–2.5 °C on-peak
  setback. The advisor's 06:00 write to 22.0 and 15:00 write to 23.0 cancel
  the *requested* value but the utility re-applies its relative offset, so
  the outcome is unchanged. Leave it.
- **Pool pump** is the largest non-EV load after the compressor and has no
  measurement. A monitoring plug (or reusing the Grizzl-E-style daemon
  pattern) would settle it; the 16:00–21:00 shedding already exists.

## 5. What was verified vs inferred

Verified from data: every number in §1–§3 and every timestamped event in
§4. Inferred: the source of the 07:00 `preset: home` setpoint change (eco+
vs comfort profile — the cloud API does not say), the pool pump wattage
(regression, R² 0.60, 23 points), and that the Fri 4 Sep 19:00 cooling would
not have happened without 4.1 (it started within the same minute as the
write, indoor was 23.1 vs the new 23.0 target).

Not checked: the ecobee eco+ configuration itself, the thermostat's own
energy report, and any month before July 2025 for tier shape.

## 6. Method

- Alectra: `UsageAPI/api/V1/Electric` and `.../Generation` with
  `Periodicity=MO|DA|HH`, hourly `tierTou` and `amount` per row. Requests
  need the portal's bearer token plus `pt: 1` and `uid: 1` headers.
  The `readDate` offset (`+01:00`) is bogus; the local hour is the hour.
- Weather: Open-Meteo archive, 43.34 N 79.90 W, daily mean/max.
- HA: `home-assistant_v2.db` opened read-only (`?mode=ro`), `states` joined
  to `state_attributes` for `climate.ecobee_3` (`equipment_running`,
  `temperature`, `preset_mode`), `climate.ecobee` (effective target),
  `input_text.climate_ai_recommendation`, `sensor.grizzl_e_total_cost`
  (`period_label`), and the pool/EV switches; `statistics` for the charger.
  Compressor time = `compCool` in `equipment_running`, time-weighted per
  hour.
- Recorder keeps 7 days, so July/August HVAC behaviour is inferred from
  the meter, not observed. The Sep 1–4 Alectra hourly rows were not yet
  posted.

## 7. Fixes deployed 2026-09-05 09:27 EDT

| Defect | File | Change |
| --- | --- | --- |
| 4.1 | `automations/10_climate_comfort.yaml` | Skip the write while `period_label` is On-Peak; new 21:01 weekday catch-up trigger applies the Evening ladder once the peak ends (21:01, not 21:00, because the label flips 3–15 s after the hour). |
| 4.2 | `automations/01_main.yaml` | New `tariff_change` state trigger on the `period_label` attribute; the advisor is `mode: queued`, so it runs after the stale :00 run instead of being dropped. One extra Gemini call per daily boundary. |
| 4.3 | `automations/01_main.yaml` | New `variables` block after the AI parse: in summer, during live On-Peak, RH ≤ 55 %, not night, the applied setpoint is floored at 25.5 °C whatever the model returned, and any on-peak coast is exempt from the two-hour hold. Reason string gets `[on-peak floor: 25.5C applied]` when the floor changed the value. Lives in its own block because re-assigning `setpoint` inside the block that defines it would be a duplicate YAML key. |
| 4.4 | `automations/06_enhancements.yaml` | Restore clamps the captured target to 22.0–25.5 °C in summer; winter unchanged. |

Self-check: `verification/test_climate_tou_guards.py` (needs PyYAML + Jinja2)
renders the real templates with stubs and asserts the Fri 4 Sep, Tue 1 Sep,
humid, mid-peak, night, winter and door-restore cases. `verification/preflight.sh`
passes. Deployed over Tailscale (LAN ssh was down): live files matched the edit
base byte-for-byte before copy; `check_config` exit 0; `automation.reload` HTTP 200
at 09:26 EDT and all three automations re-created at 09:27:08; smoke tests 11/0.
First weekday exercise of 4.1–4.3 is Mon 2026-09-07 at 16:00/21:01.
