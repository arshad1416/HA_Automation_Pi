# Plan Review Log: Kitchen lights on presence during daylight

Phases 0-1 (recon + interrogation) complete — plan locked with the user. MAX_ROUNDS=5.

Phase 0 recon produced `DIAGNOSIS-kitchen-presence.md`: the automation fires 40/41 times
after dark; 72% of walk-ins are in daylight where nothing is designed to fire.

Phase 1 resolved three load-bearing decisions (lux threshold + new knob; single automation
owner; one unified dark-day definition) and four cosmetic ones.

## Round 1 — Codex

- `condition: input_boolean.kitchen_auto_lights_disable == 'off'` is not valid HA condition syntax; use `condition: state` with `entity_id` and `state: "off"` (and express the daylight test similarly).
- Removing the top-level sun condition lets the `default` branch turn every light on when `sun.sun` is `unknown`/`unavailable`; gate the evening branch on `below_horizon` and make unknown sun state a no-op.
- The new `device_class: light` makes `on` display as “light detected” while the automation interprets it as dark; omit the device class or rename/invert the sensor.
- Replacing weather/UV with lux changes more than the documented bright-partly-cloudy case, especially winter daylight, low-sun periods, UV-unavailable states, and sensor-fallback behavior; compare those periods explicitly or retain the old test as a fallback.
- Presence restoration does not cancel an in-flight `script.kitchen_lights_step_dim`; because the script is `mode: parallel`, stale 60/35/15% calls can overwrite the new 100% state; stop the script on presence-on before restoring lights or serialize dimming.
- A presence bounce can let the old graduated-dimming run reach its delayed off decision based on the earlier absence, turning lights off shortly after re-entry; require presence to have been continuously off for the full delay before the tail.
- HA restart loses pending automation delays and may not generate a new presence-on edge, leaving lights stale or preventing restoration; add a guarded startup reconciliation for current presence and light state.
- The planned `light.turn_on` calls lack `continue_on_error`; the documented 17.9-hour main-light outage could abort the dark-day sequence or produce noisy failures; add it to each multi-entity action and keep independent light groups separate.
- During illuminance unavailability, the fallback treats low elevation as dark and treats missing cloud coverage as clear, so startup/dependency outages can produce inconsistent results; expose dependency readiness or use a conservative, explicitly documented fallback.
- `20000 lx` is not defensible as a stable all-season threshold from only eight late-August days when the plan already predicts winter all-day activation; collect seasonal data or use a solar-position/season-adjusted threshold with hysteresis.
- The disable toggle only suppresses presence restoration, not graduated dimming or sync behavior; define it as a presence-restore toggle or apply it consistently to every automation it is meant to disable.
- A simpler lower-risk rollout is to add only the above-horizon cabinet-strip branch and leave the existing weather/UV island condition unchanged until seasonal lux data validates the shared sensor.

VERDICT: REVISE
### Claude's response

**Accepted (8):**

1. **Invalid condition shorthand** — PLAN.md wrote `condition: input_boolean.x == 'off'` as prose.
   Rewritten as explicit `condition: state` blocks throughout. Correct; that would have failed
   check_config.
2. **`sun.sun` unknown/unavailable falls through to the evening branch** — the strongest finding.
   The removed top-level condition was implicitly making unknown-sun a no-op; without it the
   bare `default:` would turn all 7 lights on at 100% during a sun-integration hiccup. Choose
   restructured: three explicit branches (daylight / overnight / evening), each gated on a real
   `sun.sun` state, and **no bare `default:`** — unknown sun is now a deliberate no-op.
3. **`device_class: light` inverts the semantics** — accepted (I had flagged it myself under
   Risks). Device class dropped; sensor also now exposes `lux` and `threshold` attributes so the
   flag is debuggable from the UI without a template editor.
5. **In-flight `script.kitchen_lights_step_dim` can overwrite the restore** — accepted, and the
   frequency argument cuts the other way from my Phase 0 measurement. I measured zero occurrences
   in 7.6 days, but that was with **no daytime restore path existing at all**. Daytime dimming
   already fires 39 times per 8 days; adding a daytime restore puts both on the same clock and
   materially raises the collision rate. `script.turn_off` added at the top of the restore action.
6. **Presence bounce lets the dimming tail turn lights off after re-entry** — accepted in its
   narrow form. The tail's bare `condition: state ... "off"` becomes
   `condition: state ... "off" for: "00:02:00"`, so a bounce during the delay no longer satisfies
   it. One line; does not touch the trigger.
8. **Missing `continue_on_error`** — accepted, and directly motivated by this repo's own
   evidence: `light.kitchen_light_light_1` was unavailable 17.9 h on 08-30. Added to every
   `light.turn_on`, and the strips vs. main+island calls stay separate so one dead entity cannot
   take the other group down.
9. **Fallback treats missing `cloud_coverage` as clear** — accepted as a documentation fix. The
   `| float(0)` default fails toward "not dark", i.e. toward leaving lights off. Now stated
   explicitly rather than left implicit.
11. **Disable toggle scope** — accepted as a documentation/naming fix. It gates presence-driven
   turn-**on** only; dimming and sync are deliberately left outside it (you still want lights to
   turn off when a kill switch is engaged). Stated in the plan.

**Rejected (4), with reasons:**

4. **"Retain the old weather/UV test as a fallback."** Rejected — this reintroduces exactly the
   dual definition that Q3 eliminated, and the user was shown the measured 40% disagreement
   (280/693 samples) before choosing to unify. The seasonal concern inside this finding is real
   and is retained under Risks; the proposed fix is not. Note the disagreement was 100%
   one-directional (weather over-eager, `partlycloudy` at 44,475 lx), so the old test is not a
   safety net — it is the looser of the two.
7. **"Add a guarded startup reconciliation automation."** Rejected as over-engineering. The path
   already self-heals: `input_boolean.kitchen_tuya_presence` has `initial: false`, so an HA
   restart drives presence off, and `tuya_kitchen_bridge.py` re-pushes true state within
   `REPUSH_INTERVAL = 60` s — producing a genuine off→on edge that fires the restore. Adding a
   second startup path would create the split ownership Q2 exists to prevent.
10. **"Season-adjusted threshold with hysteresis."** Rejected. `sensor.illuminance`
   (ha-illuminance) already computes from solar position × cloud cover, so a season-adjusted
   threshold layers a second solar model on top of one that has it. Hysteresis is moot: the
   automation is edge-triggered on presence, and the sensor updates ~5-minutely — there is no
   loop to oscillate. The seasonal risk is real and is handled by the tunable knob plus an
   explicit winter re-check in Risks.
12. **"Ship only the cabinet-strip branch, leave the island alone."** Rejected — this is a
   direct reversal of Q3, which the user decided with the disagreement data in front of them.
   Logged, not silently overridden.

## Round 2 — Codex

- Findings 1, 2, 3, 5, 6, 8, 9, and 11 are addressed correctly; the explicit branches, cancellation, tail `for`, error handling, and toggle scope are materially better.
- Rejections of findings 4 and 12 are reasonable because retaining weather/UV would defeat the deliberate single-definition decision.
- Finding 7’s rejection is acceptable only if the bridge is guaranteed to restart and repush after every HA restart; otherwise the plan still has a missed-presence window. Fix: document and verify that service dependency, or add a guarded startup check.
- Finding 10 is not fully resolved: ha-illuminance modeling solar position does not make an absolute 20,000-lux threshold season-stable; the plan explicitly predicts winter all-day activation. Fix: either require seasonal calibration before deployment or derive the threshold from a normalized cloud/solar value.
- The fallback sensor is still a synthetic `on/off` state during dependency outages, so a stale but numerically valid illuminance value is trusted indefinitely. Fix: add a freshness/last-update guard or document that stale values are out of scope.
- `script.turn_off` cancels parallel fade runs, but the plan should verify that the action stops all active runs of that script rather than only the current invocation. Fix: confirm this in a smoke test before relying on it.
- The automation description remains inconsistent unless updated: it currently says the automation “does nothing while the sun is up,” although the revised plan adds daylight behavior.

VERDICT: REVISE
### Claude's response

Codex confirmed findings 1, 2, 3, 5, 6, 8, 9, 11 addressed and accepted the rejections of 4
and 12.

**Accepted (4):**

- **A — finding 7's rejection is conditional on the bridge actually restarting.** Fair
  challenge; I had asserted it rather than checked it. Now **verified empirically**:
  `tuya-kitchen-bridge.service` (`Restart=always`, `Requires=docker.service`) has been
  continuously active since 08-27 20:35:46, spanning the HA restarts at 08-28 00:32 and 00:33,
  with 140 presence state rows recorded afterwards; plus a second path via the
  `tuya_kitchen_bridge_startup` automation. Added to Assumptions with the evidence — and with
  the caveat that the systemd unit is not tracked in git, so this is host state, not repo state.
- **C — stale illuminance trusted indefinitely.** Accepted, and the measurement makes it more
  serious than Codex knew: median update gap is 300 s but the **max observed gap is 580 minutes**.
  A sensor stuck low would hold `kitchen_dark_day` on and the main light with it. Added a 1-hour
  freshness guard that falls through to the existing fallback. Safe at night by construction:
  when it trips, the fallback's `elevation < 5` limb returns the same answer.
- **D — does `script.turn_off` stop all parallel runs?** Accepted as unverified. Added as an
  explicit post-deploy smoke test rather than assumed, since the cancellation is decorative if
  it only stops one run.
- **E — stale automation description.** Correct; it still says "Does nothing while the sun is
  up". Added to the step-3 edit list.

**Held, logged as an unresolved disagreement (1):**

- **B — finding 10, seasonal threshold stability.** Neither model moved. Codex wants seasonal
  calibration before deployment or a normalized solar/cloud threshold. My position: absolute lux
  is the correct semantic for "is it dark enough to want light" — a dark December noon genuinely
  warrants the lights — whereas normalizing against clear-sky re-encodes "is it cloudy for this
  time of year", which is the question the weather/UV test already answered badly (40% wrong).
  Blocking deployment until winter ships nothing for four months. The correction costs one
  slider move and no code change. Recorded in Risks under both positions, with a dated review
  checkpoint, and flagged for the user to arbitrate. Per the loop's rules a flagged disagreement
  beats a false convergence.

## Round 3 — Codex

- Findings A, C, D, and E are addressed; the bridge evidence, one-hour freshness fallback, cancellation smoke test, and description update are sufficient.
- The seasonal-threshold disagreement is documented and is a nuisance/UX risk, not an active safety blocker; leaving it for user arbitration is reasonable.
- New minor issue: `now()` plus the changing `age_s` attribute causes the template entity to update—and likely write recorder rows—every minute, contradicting the claim that rows occur only when the state flips; expose a static `last_updated` timestamp instead or explicitly accept the recorder churn.
- The freshness guard checks entity update age, not measurement age; verify that `sensor.illuminance` updates `last_updated` on every real calculation, or use an integration-provided measurement timestamp if available.

VERDICT: APPROVED
### Claude's response

Converged: **VERDICT: APPROVED** after 3 rounds. Codex accepted A/C/D/E as addressed and
agreed the seasonal disagreement is a UX risk for the user to arbitrate, not a safety blocker.

Both minor issues raised alongside the approval were accepted rather than waved through:

- **`age_s` causes per-minute recorder churn.** Correct, and my note in the plan was actively
  wrong — I had written that rows are written only when the state flips. Attribute changes do
  create rows; this session verified both directions (automation entities churn rows even with
  unchanged attributes, while light `brightness` writes none because it is an excluded
  attribute). Replaced with `source_updated`, a static timestamp that moves only when
  `sensor.illuminance` moves, so recorder churn matches the source's ~5-minute rate rather than
  the 1-minute render clock.
- **The guard measures entity update age, not measurement age.** Accepted as a real caveat.
  It is a safe proxy *only* because the value is a continuously-varying computation — measured:
  1,451 rows with no two consecutive identical values. Documented, including how it would
  silently weaken if ha-illuminance ever started emitting rounded values.

Loop complete. No code has been written; awaiting user sign-off before implementation.

## Post-build inspection

Builder: Claude. Inspector: a FRESH read-only Codex session (thread 01a05b0c-…, new
thread — not the Phase 2 review thread, so it saw the code cold). 2 rounds, the cap.

### Round 1 findings (verbatim)

- **SPEC/EDGE REGRESSION:** `sun.sun` unknown/unavailable does not produce a true no-op. The `choose` correctly matches no branch, but preceding actions still cancel all parallel dim runs and release adaptive-lighting manual control. A presence event during a sun integration outage can therefore stop the dim/off sequence without restoring the lights.

- **CORRECTNESS:** No blocking `check_config` issue found by inspection. The YAML structure, `choose` branches, nested `if`, service names, and `continue_on_error` placement are valid.

- The binary sensor template is safe: both limbs render Jinja booleans, which HA accepts for a template binary sensor. Missing entities are handled by the short-circuit `s is not none`; unavailable/stale readings correctly reach the fallback.

- The three branches are correctly ordered and explicitly gated. Daylight wins before overnight, and unknown sun has no light-turn-on branch.

- The `kitchen_light_sync` replacement is structurally valid; its existing pre-sunrise `not` guard remains intact.

- Unavailable/stale illuminance fails closed during daytime; missing cloud data defaults to leaving main/island lights off. HA restart behavior is unchanged and relies on the documented external bridge assumption.

Nothing else blocking found.
### Claude's dispositions

- **ACCEPTED — `sun.sun` unknown was not a true no-op.** A genuine regression I introduced, and
  the one thing the inspection was worth running for. `script.turn_off` and the
  adaptive-lighting release run *before* the `choose`; with an unknown sun no branch matched, so
  those two fired and nothing came back up — cancelling an in-flight fade and handing the strips
  back to AL while leaving them stranded mid-ladder. The old top-level `below_horizon` condition
  had been making the whole automation a no-op in that case, and my rewrite silently dropped that
  property while appearing to preserve it via per-branch gates. Fixed with a top-level
  `condition: state / sun.sun / [above_horizon, below_horizon]`, which restores the exact prior
  semantics without blocking the daylight branch. Per-branch sun gates kept as defence in depth
  and to keep the absence of a bare `default:` self-evident.
- Everything else in round 1 was confirmation, not a finding: no `check_config` blocker, template
  renders on both limbs, `s is not none` short-circuit is safe for a missing entity, branch
  ordering correct, `kitchen_light_sync` `if` still structurally valid.

### Round 2 findings

- **Fix confirmed** correct and complete; nothing broken, nothing new.
- **ACCEPTED (non-blocking) — stale comment.** The graduated-dimming automation still claimed
  the restore "only runs after sunset, and during the day nothing else was releasing manual
  control". The daylight branch makes both halves false. Comment rewritten.

Rounds used: 2 of MAX_INSPECTION_ROUNDS=2. No findings rejected.

## Deployment

Deployed to `/opt/homeassistant` on the Pi, 2026-08-31 ~23:46 EDT. HA **not** reloaded.

Pre-deploy safety checks:
- Pi HEAD was `db89e3ef`, ahead of the worktree base `b3532d1f` — but all three target files
  were byte-identical to base (md5 match on each), so no Pi-side change was clobbered.
- Only unrelated files were dirty on the Pi (`www/vinfast_*.json`).

`check_config` result: **EXIT=0** over a 7,653-line full parse (`--info all`). All grep hits for
"error"/"warning" were false positives — `max_exceeded: WARNING` is HA's default value,
`continue_on_error` matches on "error", and the rest were the words appearing inside
human-readable `description:`/`title:` strings.

Positively confirmed in the parsed config (not just a non-failure):
- `unique_id: kitchen_dark_day` at `configuration.yaml:897`
- `kitchen_dark_lux` present (3 references)
- the restore automation's two top-level conditions parsed exactly as intended:
  `input_boolean.kitchen_auto_lights_disable` → `state: off` (line 323), and
  `sun.sun` → `state: [above_horizon, below_horizon]` (line 333)

Note: the Pi's `git-sync.sh` cron (:02/:17/:32/:47) will auto-commit and push these files to
`origin/main` on its next run, independently of whether HA has reloaded them.

**Still outstanding — the three smoke tests can only run after a reload:**
1. `script.turn_off` stops *all* parallel runs of `kitchen_lights_step_dim`.
2. `binary_sensor.kitchen_dark_day` renders on both limbs (flip `kitchen_dark_lux` across the
   current `sensor.illuminance` reading and watch the state change; check `source_updated`).
3. A walk-in between sunrise and 09:00 with `bedtime_shutdown_done` still on takes the daylight
   branch (strips 100%), not the overnight branch (strips 50%).

## Reload

Reloaded 2026-08-31 23:49:21 EDT via `docker restart homeassistant` (HA responding again after
21 s). A targeted `automation.reload` + `template.reload` would have been zero-downtime, but the
repo's convention supplies `HA_TOKEN` from the user's env and it is not stored in the repo —
minting or requesting credentials was not appropriate, so the documented container restart was
used instead.

**Verified live after reload:**

| check | result |
|---|---|
| `binary_sensor.kitchen_dark_day` | **on** — attrs `lux: 0, threshold: 20000.0, source_updated: 03:49:49Z` |
| `input_number.kitchen_dark_lux` | `20000.0` |
| all 4 kitchen automations | loaded, state `on` |
| tuya bridge | systemd active, exactly **one** process (no duplicate fighting the Tuya session) |
| HA log errors | only pre-existing Bluetooth `NET_ADMIN` capability errors; nothing kitchen-related |
| git-sync | auto-committed and pushed at 23:47:01 (`2469851d`) |

The sensor is rendering via the **primary lux limb**, not the fallback: `lux: 0` with a
`source_updated` 3 minutes old means `fresh` was true and `0 < 20000` evaluated — so the
template's main path is proven live.

**Method note — a false alarm worth recording.** Immediately after the restart,
`binary_sensor.kitchen_dark_day` was absent from both `states_meta` and
`.storage/core.entity_registry`, which looked like the entity had failed to instantiate. It had
not. The registry file's mtime (23:49:26) *predated* HA's own start (23:49:31) — it was the
pre-restart flush, and HA's registry save is debounced. It flushed at 23:52:31 and the entity was
there. Reading a `.storage` file is only valid evidence if its mtime is later than the current
run's start.

**Smoke tests — honest status:**

1. `script.turn_off` stops *all* parallel runs — **NOT TESTED.** Needs a service call.
2. `kitchen_dark_day` renders on both limbs — **PARTIAL.** Primary lux limb proven live; the
   stale/unavailable fallback limb has not been exercised.
3. Daylight branch beats the overnight branch — **NOT TESTABLE YET.** Sun is below the horizon;
   this needs a walk-in between sunrise and 09:00.
