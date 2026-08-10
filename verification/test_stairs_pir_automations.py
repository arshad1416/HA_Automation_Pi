#!/usr/bin/env python3
"""Invariant checks for the two stair-PIR automations.

These failure modes stay silent in HA — a wrong mode or a missing guard does not
raise, it just leaves the hallway panels burning at full brightness all night.
That is not hypothetical: the first version of this automation waited for
binary_sensor.pir_motion_sensor_2_motion to report 'off', which that sensor never
does (battery Tuya PIR: it pulses 'on' and sleeps to 'unavailable'). The panels
stayed lit until someone noticed. Several assertions below exist to pin that.

Both automations key off the same sensor and both had the same dead-trigger bug.
Run from anywhere:  python3 verification/test_stairs_pir_automations.py
"""
import glob
import json
import os
import re
import sys

import yaml


class HALoader(yaml.SafeLoader):
    """Accepts HA local tags (!include, !secret, ...) without resolving them."""


HALoader.add_multi_constructor("!", lambda loader, suffix, node: None)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANELS = [
    "light.hallway_nanoleaf_light_panels_left",
    "light.hallway_nanoleaf_hallway_lights_right",
]
CLAIM = "input_boolean.hallway_panels_pir_owned"
PIR = "binary_sensor.pir_motion_sensor_2_motion"
RESTORE_AFTER = {"minutes": 5}
# The owner's after-sunset resting state for this hallway: the panels' own stored
# "night light" scene at 10%. The revert is this FIXED target, not a snapshot —
# deterministic and self-healing if the panels drift.
# motion brightness per period, dimmest when the house is asleep
# Motion boosts by this many percentage points over whatever AL currently holds.
BOOST_PP = 30
# The device-side scene the panels rest on after bedtime, and its level.
NIGHT_SCENE = "night light"
NIGHT_PCT = 5
# The stair light has two legs: a dim one sourced from a tunable helper, and a literal
# bright one. Both are asserted — the bright leg previously had no value assertion at all,
# so swapping its 100 for any other number went undetected.
STAIR_BRIGHT_PCT = 100
STAIR_DIM_SOURCE = "input_number.nightly_dim_brightness"
# The AL instance scoped to these panels (configuration.yaml, 1800-6500 K). Deliberately
# NOT the Whole House instance, whose 2500 K floor suits outdoor downlights.
AL_SWITCH = "switch.hallway_panels_adaptive_lighting_hallway_panels"
STAIR_LIGHT = "light.stair_light"
CLAIM_STAIRS = "input_boolean.stair_light_pir_owned"
# The single boundary between the two automations (configuration.yaml template sensor).
BOUNDARY = "binary_sensor.after_bedtime"


def load_automations():
    out = []
    for path in sorted(glob.glob(os.path.join(REPO, "automations", "*.yaml"))):
        with open(path) as fh:
            for doc in yaml.load_all(fh, Loader=HALoader):
                if isinstance(doc, list):
                    out += [a for a in doc if isinstance(a, dict)]
    return out


def branch_for(auto, trigger_id):
    for option in auto["actions"][0]["choose"]:
        for cond in option["conditions"]:
            if cond.get("condition") == "trigger" and cond.get("id") == trigger_id:
                return option
    raise AssertionError(f"no choose branch for trigger id {trigger_id!r}")


def steps_of(seq):
    return [s.get("action") for s in seq]


def assert_no_dead_pir_trigger(auto):
    """The PIR never reports 'off' — any trigger waiting for that is dead code.

    Measured 2026-08-08: 17 state changes in 8 hours, every one on <-> unavailable,
    never once 'off'. It is a battery Tuya PIR that pulses on motion and sleeps to
    'unavailable'. Both stair automations shipped with a `to: 'off'` trigger as their
    only turn-off path, so neither ever turned its light back off.
    """
    for trig in auto["triggers"]:
        ents = trig.get("entity_id")
        ents = [ents] if isinstance(ents, str) else (ents or [])
        if PIR in ents:
            assert trig.get("to") != "off", (
                f"{auto['id']}: trigger {trig.get('id')!r} waits for {PIR} to report "
                "'off'. That sensor never does — this trigger can never fire, which is "
                "the exact bug that left the light stuck on."
            )


def assert_is_revert(step):
    """The resting state, which differs by period.

    Sun up means this cycle was the dark-day case and the panels must go OFF — they are
    not meant to sit lit in daylight. Otherwise they return to the 10% "night light"
    look. Evaluated at revert time, not motion time, so a cycle spanning sunset settles
    into the correct end state.
    """
    assert "if" in step, f"the revert must branch on sun position, got {step}"
    assert any(
        c.get("entity_id") == "sun.sun" and c.get("state") == "above_horizon"
        for c in step["if"]
    ), "the revert must test sun.sun above_horizon to detect the dark-day case"

    day = step["then"]
    assert [x.get("action") for x in day] == ["light.turn_off"], (
        f"dark-day revert must turn the panels OFF, got {[x.get('action') for x in day]}"
    )
    assert sorted(day[0]["target"]["entity_id"]) == sorted(PANELS)

    # The night side is a 3-way now: after bedtime the night-light scene is the resting
    # look; before bedtime AL owns it and control is handed back.
    night = step["else"]
    assert len(night) == 1 and "if" in night[0], (
        f"night revert must branch on {BOUNDARY}, got {[x.get('action') for x in night]}"
    )
    inner = night[0]
    assert any(c.get("entity_id") == BOUNDARY and c.get("state") == "on"
               for c in inner["if"]), "the night branch must test after_bedtime"

    bed = inner["then"]
    assert [x.get("action") for x in bed] == [
        "adaptive_lighting.set_manual_control", "light.turn_on"], (
        f"bedtime resting state must park AL then set the scene, got "
        f"{[x.get('action') for x in bed]}"
    )
    assert bed[0]["data"].get("manual_control") is True, (
        "AL must be PARKED (manual_control: true) before the scene is set — it writes "
        "brightness and colour every tick and would wipe the effect within a minute"
    )
    assert bed[1]["data"].get("effect") == NIGHT_SCENE
    assert bed[1]["data"].get("brightness_pct") == NIGHT_PCT
    assert sorted(bed[1]["target"]["entity_id"]) == sorted(PANELS)

    pre = inner["else"]
    assert [x.get("action") for x in pre] == [
        "adaptive_lighting.set_manual_control", "adaptive_lighting.apply"], (
        f"pre-bedtime resting state must hand control back to AL, got "
        f"{[x.get('action') for x in pre]}"
    )
    assert pre[0]["data"].get("manual_control") is False, (
        "must CLEAR manual_control — the boost parks AL, and without clearing it AL "
        "never resumes adapting"
    )
    assert pre[1]["data"].get("adapt_brightness") is True
    assert pre[1]["data"].get("adapt_color") is True
    for st_ in pre:
        dd = st_.get("data", {})
        for forbidden in ("brightness_pct", "effect", "color_temp_kelvin", "hs_color"):
            assert forbidden not in dd, f"{forbidden} here re-takes control from AL"


def check_bedtime_scene(by_id):
    """At the bedtime boundary the panels switch to the night-light scene.

    The scene lives on the devices and cannot survive AL adaptation, so the bedtime branch
    parks AL first and the morning branch un-parks it. Forgetting the morning un-park is
    the quiet failure: AL stays stood off all day and never follows the curve again.
    """
    auto = by_id.get("hallway_panels_bedtime_scene")
    assert auto is not None, "hallway_panels_bedtime_scene is missing"
    ids = {t.get("id") for t in auto["triggers"]}
    assert ids == {"bedtime", "morning"}, f"unexpected triggers: {ids}"
    for t in auto["triggers"]:
        assert t["entity_id"] == BOUNDARY, f"must key off {BOUNDARY}"

    bed = branch_for(auto, "bedtime")["sequence"]
    assert [x.get("action") for x in bed] == [
        "adaptive_lighting.set_manual_control", "light.turn_on"]
    assert bed[0]["data"].get("manual_control") is True, "must park AL before the scene"
    assert bed[1]["data"].get("effect") == NIGHT_SCENE
    assert bed[1]["data"].get("brightness_pct") == NIGHT_PCT

    morn = branch_for(auto, "morning")["sequence"]
    assert [x.get("action") for x in morn] == [
        "adaptive_lighting.set_manual_control", "adaptive_lighting.apply"], (
        "the morning branch must un-park AL and re-apply, or AL stays stood off all day"
    )
    assert morn[0]["data"].get("manual_control") is False, (
        "morning must CLEAR manual_control — otherwise AL never adapts these panels again"
    )


def check_no_overnight_full_brightness(by_id):
    """The stair light's two brightness legs: reachable, and emitting the right values.

    `{% if now().hour >= dim_hr %}` alone is False for every hour from 00:00 to dim_hr
    (21/22/23), so the dim leg was unreachable overnight and every small-hours trip took
    100%. Proven reachable in practice: the bedtime latch sat OFF continuously from
    2026-08-02 20:00 to 2026-08-04 00:41 — a whole night, HA up and recording.
    """
    stairs = by_id["stairs_pir_motion_light"]
    branch = next(
        o for o in stairs["actions"][0]["choose"]
        if any(c.get("condition") == "trigger" and c.get("id") == "motion" for c in o["conditions"])
    )
    turn_on = next(x for x in branch["sequence"] if x.get("action") == "light.turn_on")
    tpl = str(turn_on["data"]["brightness_pct"])
    assert "now().hour >= dim_hr" in tpl, "the seasonal dim-hour logic disappeared"
    assert "now().hour < 12" in tpl and "below_horizon" in tpl, (
        "the dim leg must run from the dim hour to sunrise — `now().hour >= dim_hr` alone "
        f"is false all night and the stairs fire at 100% at 2am: {tpl!r}"
    )

    # --- both legs must still emit what they claim ------------------------------
    # Same emitted-legs technique as the panels: match a number only where it is emitted
    # straight after a %} tag, so the {% set dim_hr %} prelude's [3,4,9,10] month list
    # cannot satisfy it. The bright leg is the only literal the template emits; the dim
    # leg is an expression, so it contributes no literal here.
    legs = [int(x) for x in re.findall(r"%\}\s*(\d+)", tpl)]
    assert legs == [STAIR_BRIGHT_PCT], (
        f"stair light bright leg drifted: emits {legs}, expected [{STAIR_BRIGHT_PCT}]"
    )
    # The dim leg must stay tunable rather than being frozen to a literal — the helper is
    # how the seasonal night level is adjusted without editing this file.
    assert STAIR_DIM_SOURCE in tpl, (
        f"the dim leg must read {STAIR_DIM_SOURCE}, not a hardcoded value: {tpl!r}"
    )


def check_pir_watchdog(by_id):
    """The stuck-sensor watchdog must actually be able to clear the latch.

    The PIR never reports its own clear, so both stair automations are dead until something
    resets it. Two things here are load-bearing and easy to break by "tidying":
      - the reload must pass entry_id in data. target: entity_id returns HTTP 400 despite
        the service schema advertising target support (tested 2026-08-09).
      - the alert must be conditional on the reload having FAILED. Alerting on every
        successful self-heal is how a watchdog gets muted.
    """
    auto = by_id.get("stair_pir_stuck_watchdog")
    assert auto is not None, "the PIR stuck-sensor watchdog is missing"
    assert auto["mode"] == "single", "watchdog must be mode: single or reloads can overlap"
    ids = {t.get("id") for t in auto["triggers"]}
    assert ids == {"stuck_on", "offline"}, f"unexpected watchdog triggers: {ids}"

    stuck = next(t for t in auto["triggers"] if t["id"] == "stuck_on")
    assert stuck["entity_id"] == PIR and stuck.get("to") == "on"
    assert stuck.get("for", {}).get("minutes", 0) >= 10, (
        "too twitchy: a short window would reload Tuya on ordinary lingering"
    )

    acts = auto["actions"]
    reload_step = next((a for a in acts if a.get("action") == "homeassistant.reload_config_entry"), None)
    assert reload_step is not None, "the watchdog must reload the Tuya entry to clear the latch"
    assert "entry_id" in (reload_step.get("data") or {}), (
        "reload must pass data.entry_id — target: entity_id is rejected with HTTP 400"
    )
    assert "target" not in reload_step, "target form does not work for this service"

    assert any("delay" in a for a in acts), "must wait for the entry to come back before judging"
    tail = next((a for a in acts if "if" in a), None)
    assert tail is not None, "the alert must be conditional, not unconditional"
    notif = json.dumps(tail.get("then", []))
    assert "notify." in notif, "the conditional branch must notify"


def check_bedtime_latch_does_not_survive_restart():
    """input_boolean.bedtime_shutdown_done must be initial: false.

    Its 20:00 reset has no startup catch-up, so a restored ON latch after an outage across
    20:00 persists until 20:00 the NEXT day, making after_bedtime read ON all evening and
    handing the staircase to the panels while the household is still up.
    """
    import re
    path = os.path.join(REPO, "configuration.yaml")
    with open(path) as fh:
        cfg = fh.read()
    m = re.search(r"^  bedtime_shutdown_done:\n((?:    .*\n)+)", cfg, re.M)
    assert m, "bedtime_shutdown_done not found in configuration.yaml"
    assert re.search(r"^    initial:\s*false\s*$", m.group(1), re.M), (
        "bedtime_shutdown_done must be 'initial: false' so a restart cannot strand the "
        f"latch ON until 20:00 the next day. Got:\n{m.group(1)}"
    )


def check_stair_light_covers_dead_panels(by_id):
    """After bedtime the stair light stands down — unless the panels cannot answer.

    The panels are on the top landing; light.stair_light is the only fixture on the treads
    themselves. Gating the stair light off after bedtime means an unavailable Nanoleaf
    leaves the staircase completely dark at 02:00. The guard must therefore also fire when
    either panel is unavailable/unknown.
    """
    stairs = by_id["stairs_pir_motion_light"]
    branch = next(
        o for o in stairs["actions"][0]["choose"]
        if any(c.get("condition") == "trigger" and c.get("id") == "motion" for c in o["conditions"])
    )
    guard = next(
        (c for c in branch["conditions"] if BOUNDARY in str(c.get("value_template", ""))), None
    )
    assert guard is not None, f"stair light must be gated on {BOUNDARY}"
    tpl = guard["value_template"]
    assert "not is_state" in tpl, (
        "guard must be 'not is_state(..., on)' so it still fires when the boundary sensor "
        "is unknown/unavailable"
    )
    for panel in PANELS:
        assert panel in tpl, (
            f"the stair-light guard must fall back to firing when {panel} is unavailable, "
            "otherwise a dead panel after bedtime leaves the treads unlit"
        )
    assert "unavailable" in tpl and "unknown" in tpl


def check_stairs_light(by_id):
    """stairs_pir_motion_light: same sensor, same fix — timer tail instead of no_motion."""
    auto = by_id.get("stairs_pir_motion_light")
    assert auto is not None, "automation stairs_pir_motion_light is missing"

    assert_no_dead_pir_trigger(auto)
    assert auto["mode"] == "restart", (
        f"mode must be 'restart' so motion pulses extend the window, got {auto['mode']!r}"
    )
    assert {t.get("id") for t in auto["triggers"]} == {
        "motion", "light_went_off", "stuck_guard"
    }, "unexpected trigger ids"

    # light_went_off must only drop the claim, never act on the light.
    went_off = branch_for(auto, "light_went_off")
    assert steps_of(went_off["sequence"]) == ["input_boolean.turn_off"]

    # Backstop releases the claim before switching off, so light.turn_off cannot race
    # light_went_off back into an inconsistent claim.
    stuck = branch_for(auto, "stuck_guard")
    n = steps_of(stuck["sequence"])
    assert n.index("input_boolean.turn_off") < n.index("light.turn_off")

    # The motion branch must still refuse to touch an already-lit staircase.
    motion_branches = [
        o for o in auto["actions"][0]["choose"]
        if any(c.get("condition") == "trigger" and c.get("id") == "motion"
               for c in o["conditions"])
    ]
    assert len(motion_branches) == 1, (
        f"expected only the dark branch (the bedtime branch handed over to the hallway "
        f"panels), got {len(motion_branches)}"
    )
    for b in motion_branches:
        assert any(
            c.get("entity_id") == STAIR_LIGHT and c.get("state") == "off"
            for c in b["conditions"]
        ), "motion branch must require the light to be off before claiming it"
        assert steps_of(b["sequence"])[-1] == "input_boolean.turn_on", (
            "each motion branch must claim the light last"
        )

    # --- the shared timer tail, which is what actually turns the light off ---
    tail = auto["actions"][1:]
    assert tail, "the timer tail after the choose block is missing — nothing turns the light off"
    assert tail[0].get("condition") == "trigger" and tail[0].get("id") == "motion", (
        "the tail must be gated on the motion trigger, or light_went_off/stuck_guard runs "
        "would fall through into it"
    )
    # Must confirm ownership BEFORE sleeping, so a manually lit staircase is never armed.
    pre = [s for s in tail[:3] if s.get("entity_id") == CLAIM_STAIRS and s.get("state") == "on"]
    assert pre, "the tail must verify the claim before starting the delay"

    delay_i = next(i for i, s in enumerate(tail) if "delay" in s)
    assert tail[delay_i]["delay"] == RESTORE_AFTER, (
        f"expected a {RESTORE_AFTER} delay, got {tail[delay_i]['delay']}"
    )
    after = tail[delay_i + 1:]
    assert any(
        s.get("condition") == "state" and s.get("entity_id") == CLAIM_STAIRS
        and s.get("state") == "on" for s in after
    ), "must re-check the claim after the delay before switching off"
    acts = [s.get("action") for s in after if s.get("action")]
    assert acts.index("input_boolean.turn_off") < acts.index("light.turn_off"), (
        "claim must be released before light.turn_off, otherwise the resulting "
        "light_went_off restart races the claim"
    )


def main():
    autos = load_automations()
    by_id = {a.get("id"): a for a in autos}
    auto = by_id.get("hallway_panels_stairs_pir")
    assert auto is not None, "automation hallway_panels_stairs_pir is missing"

    assert_no_dead_pir_trigger(auto)

    # --- mode: restart is load-bearing -----------------------------------
    # It is what makes a new motion pulse cancel the pending restore and re-arm it.
    # Under 'queued' every pulse would queue its own restore and the panels would
    # drop 5 minutes after the FIRST pulse while someone was still on the stairs.
    assert auto["mode"] == "restart", (
        f"mode must be 'restart' so motion pulses extend the window, got {auto['mode']!r}"
    )

    trigger_ids = {t.get("id") for t in auto["triggers"]}
    assert trigger_ids == {"motion", "panels_went_off", "stuck_guard"}, (
        f"unexpected trigger ids: {trigger_ids}"
    )

    release = next(t for t in auto["triggers"] if t.get("id") == "panels_went_off")
    assert sorted(release["entity_id"]) == sorted(PANELS) and release.get("to") == "off"

    guard = next(t for t in auto["triggers"] if t.get("id") == "stuck_guard")
    assert guard["entity_id"] == CLAIM and guard.get("to") == "on"
    assert guard.get("for", {}).get("minutes", 0) > RESTORE_AFTER["minutes"], (
        "the stuck_guard must be longer than the normal restore delay, or it will "
        "fire during healthy runs"
    )

    # --- release branch only drops the claim -----------------------------
    went_off = branch_for(auto, "panels_went_off")
    assert steps_of(went_off["sequence"]) == ["input_boolean.turn_off"], (
        "the release branch must only drop the claim — anything else fights manual control"
    )

    # --- backstop restores, claim released first -------------------------
    stuck = branch_for(auto, "stuck_guard")
    names = steps_of(stuck["sequence"])
    # Claim released first, then the revert (an if/else, so it has no "action" key).
    assert names[0] == "input_boolean.turn_off", (
        f"stuck_guard must release the claim first, got {names}"
    )
    assert_is_revert(stuck["sequence"][-1])

    # --- motion branch ----------------------------------------------------
    motion = branch_for(auto, "motion")
    # The panels now act in three periods, so the gate is an OR, not a bare sunset check.
    # Plain daylight that is not dark enough must match nothing and leave the panels alone.
    period_or = next(
        (c for c in motion["conditions"] if c.get("condition") == "or"), None
    )
    assert period_or is not None, "motion branch must gate on an OR of the three periods"
    inner = period_or["conditions"]
    assert any(c.get("entity_id") == BOUNDARY and c.get("state") == "on" for c in inner), (
        "after-bedtime period missing from the gate"
    )
    assert any(
        c.get("entity_id") == "sun.sun" and c.get("state") == "below_horizon" for c in inner
    ), "after-sunset period missing from the gate"
    assert any(
        "illuminance" in str(c.get("value_template", "")) and "stairs_dark_lux" in str(c.get("value_template", ""))
        for c in inner
    ), "dark-day period must key off sensor.illuminance vs input_number.stairs_dark_lux"

    seq = motion["sequence"]

    # The claim is taken only when not already held, so a repeat pulse cannot re-take a
    # claim that something else released while the panels were up.
    guard_if = seq[0]
    assert "if" in guard_if, "first step must be the claim guard"
    assert any(
        c.get("entity_id") == CLAIM and c.get("state") == "off" for c in guard_if["if"]
    ), "the claim must only be taken when not already held"
    assert steps_of(guard_if["then"]) == ["input_boolean.turn_on"], (
        f"guarded block must only claim, got {steps_of(guard_if['then'])}"
    )

    delay_at = next(i for i, s in enumerate(seq) if "delay" in s)
    turn_on = next(s for s in seq[:delay_at] if s.get("action") == "light.turn_on")
    assert "data" in turn_on and "brightness_pct" in turn_on["data"], (
        "the motion step must pass a brightness — a bare turn_on comes up at AL's ambient "
        "level (the 10 percent floor by bedtime), which is not a boost at all"
    )
    bri = str(turn_on["data"]["brightness_pct"])
    # Motion BOOSTS relative to AL's current level. A fixed tier would fight AL's ramp.
    assert AL_SWITCH in bri and "brightness_pct" in bri, (
        f"motion brightness must derive from {AL_SWITCH}'s brightness_pct so it is a boost "
        f"over AL's current level, got {bri!r}"
    )
    assert "100" in bri and "| min" in bri, "the boost must be capped at 100 via min()"
    # The fallback (used only if the AL switch disappears) must match AL's configured
    # floor, or a missing switch silently degrades to a different brightness than the
    # curve would ever produce. These two live in different files and drifted once.
    import re as _re
    fb = _re.search(r"brightness_pct'\)\s*\|\s*float\((\d+)\)", bri)
    assert fb, f"could not find the boost fallback in {bri!r}"
    cfg = open(os.path.join(REPO, "configuration.yaml")).read()
    floor = _re.search(r"^    min_brightness:\s*(\d+)", cfg, _re.M)
    assert floor, "min_brightness not found in configuration.yaml"
    assert fb.group(1) == floor.group(1), (
        f"boost fallback float({fb.group(1)}) does not match AL min_brightness "
        f"{floor.group(1)} in configuration.yaml — they must stay in step"
    )
    # Colour is deliberately absent: AL owns it and re-applies on its own tick.
    assert "color_temp_kelvin" not in turn_on["data"], (
        "the boost must not set colour — AL owns it; passing one just fights the curve"
    )
    assert "effect" not in turn_on["data"], (
        "an effect here would be wiped by AL's next brightness/colour write"
    )
    assert sorted(turn_on["target"]["entity_id"]) == sorted(PANELS)

    # Brightness and colour must ship in ONE call. Measured 2026-08-08: a separate
    # adaptive_lighting.apply overrode brightness to 254 even with adapt_brightness
    # false, which is why the panels came up at full instead of 50%.
    assert not any(s.get("action") == "adaptive_lighting.apply" for s in seq), (
        "adaptive_lighting.apply overrides brightness even with adapt_brightness: false "
        "(AL 1.30.1) — read AL's colour off its switch attribute in the same light.turn_on "
        "instead, so brightness and colour are atomic"
    )
    # Exactly one turn_on BEFORE the delay. A second call there could land between
    # brightness and colour and override one of them (which adaptive_lighting.apply did).
    assert len([s for s in seq[:delay_at] if s.get("action") == "light.turn_on"]) == 1, (
        "exactly one light.turn_on before the delay: a second can override the first"
    )
    # --- the restore tail -------------------------------------------------
    delay_i = next(i for i, s in enumerate(seq) if "delay" in s)
    assert seq[delay_i]["delay"] == RESTORE_AFTER, (
        f"expected a {RESTORE_AFTER} delay, got {seq[delay_i]['delay']}"
    )
    tail = seq[delay_i + 1:]
    # Must re-check the claim after waking: something may have released it while we slept.
    assert any(
        s.get("condition") == "state" and s.get("entity_id") == CLAIM
        and s.get("state") == "on" for s in tail
    ), "must re-check the claim after the delay before restoring"
    tail_actions = [s.get("action") for s in tail if s.get("action")]
    assert "input_boolean.turn_off" in tail_actions, "the tail must release the claim"
    release_at = next(i for i, x in enumerate(tail) if x.get("action") == "input_boolean.turn_off")
    revert_at = len(tail) - 1
    assert release_at < revert_at, (
        "claim must be released before the revert, otherwise the revert switching a panel "
        "off re-enters panels_went_off and races the claim"
    )
    assert_is_revert(tail[revert_at])
    # Nothing may depend on a scene: scene.create scenes do not survive an HA restart, and
    # a fixed revert has no such failure mode.
    assert not any("scene." in str(s.get("action", "")) for s in seq), (
        "the revert must be a fixed light.turn_on, not a scene replay"
    )

    # --- the two automations must drive disjoint lights ---------------------
    # They share a sensor and deliberately overlap in time, but neither may operate the
    # other's fixture. Checked against real service targets, not raw text: the stairs
    # automation legitimately *references* the panels in its availability fallback.
    stairs = by_id.get("stairs_pir_motion_light")
    assert stairs is not None, "stairs_pir_motion_light disappeared"

    def light_targets(node, out):
        if isinstance(node, dict):
            act = node.get("action")
            if isinstance(act, str) and act.startswith("light."):
                ent = (node.get("target") or {}).get("entity_id")
                out.update([ent] if isinstance(ent, str) else (ent or []))
            for v in node.values():
                light_targets(v, out)
        elif isinstance(node, list):
            for v in node:
                light_targets(v, out)

    stairs_drives = set()
    light_targets(stairs.get("actions"), stairs_drives)
    panels_drives = set()
    light_targets(auto.get("actions"), panels_drives)

    for panel in PANELS:
        assert panel not in stairs_drives, (
            f"stairs_pir_motion_light drives {panel} — the two automations must not both "
            "operate the panels"
        )
    assert STAIR_LIGHT not in panels_drives, (
        f"hallway_panels_stairs_pir drives {STAIR_LIGHT} — it must only drive the panels"
    )
    assert panels_drives == set(PANELS), f"panels automation drives {panels_drives}"
    assert stairs_drives == {STAIR_LIGHT}, f"stairs automation drives {stairs_drives}"

    # --- no dangling Nanoleaf Elements entity ------------------------------
    for path in sorted(glob.glob(os.path.join(REPO, "automations", "*.yaml"))):
        with open(path) as fh:
            body = fh.read()
        assert "light.elements_b3cd_2" not in body, (
            f"{os.path.basename(path)} still references light.elements_b3cd_2"
        )

    check_stairs_light(by_id)
    check_stair_light_covers_dead_panels(by_id)
    check_no_overnight_full_brightness(by_id)
    check_bedtime_latch_does_not_survive_restart()
    check_pir_watchdog(by_id)
    check_bedtime_scene(by_id)

    print("stairs PIR automations (both): all invariants OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
