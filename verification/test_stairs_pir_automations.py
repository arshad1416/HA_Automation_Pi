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
import os
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
# Brightness the PIR branch drives the panels to. Changing this must also change
# the automation's alias, which advertises the value to the user.
BRIGHTNESS_PCT = 50
RESTORE_AFTER = {"minutes": 5}
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


def check_boundary_is_complementary(by_id):
    """Exactly one of the two automations may respond to a given motion pulse.

    They must not both fire (the user asked for one light per trip) and — far more
    importantly — there must be no state of the boundary sensor where NEITHER fires,
    which would mean a dark staircase at night.

    The panels require it to be definitively 'on'. The stair light must therefore be
    written as "not on" rather than "== off": a state condition on 'off' also fails while
    the sensor is unknown/unavailable, and then neither automation would act.
    """
    stairs = by_id["stairs_pir_motion_light"]
    panels = by_id["hallway_panels_stairs_pir"]

    def motion_conditions(auto):
        for o in auto["actions"][0]["choose"]:
            if any(c.get("condition") == "trigger" and c.get("id") == "motion"
                   for c in o["conditions"]):
                return o["conditions"]
        raise AssertionError(f"{auto['id']}: no motion branch")

    p_guard = [c for c in motion_conditions(panels) if c.get("entity_id") == BOUNDARY]
    assert p_guard, f"hallway panels must be gated on {BOUNDARY}"
    assert p_guard[0].get("state") == "on", (
        f"hallway panels must require {BOUNDARY} == 'on' (after bedtime)"
    )

    s_guard = [c for c in motion_conditions(stairs)
               if BOUNDARY in str(c.get("value_template", "")) or c.get("entity_id") == BOUNDARY]
    assert s_guard, f"stair light must be gated on {BOUNDARY}"
    g = s_guard[0]
    assert g.get("condition") == "template" and "not is_state" in g.get("value_template", ""), (
        "the stair light guard must be a template 'not is_state(..., \'on\')' so it still "
        "fires when the boundary sensor is unknown/unavailable. A plain state condition on "
        "'off' leaves a window where NEITHER light responds — a dark staircase at night."
    )
    assert f"'{BOUNDARY}'" in g["value_template"] or f'"{BOUNDARY}"' in g["value_template"]


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

    # Both motion branches must still refuse to touch an already-lit staircase.
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
    assert names.index("input_boolean.turn_off") < names.index("scene.turn_on")

    # --- motion branch ----------------------------------------------------
    motion = branch_for(auto, "motion")
    assert any(
        c.get("entity_id") == "sun.sun" and c.get("state") == "below_horizon"
        for c in motion["conditions"]
    ), "motion branch must be gated on sunset"

    seq = motion["sequence"]

    # Snapshot happens only when unclaimed, so repeat pulses cannot overwrite it
    # with our own 50% state (which would make "previous state" mean "50%").
    guard_if = seq[0]
    assert "if" in guard_if, "first step must be the claim guard around the snapshot"
    assert any(
        c.get("entity_id") == CLAIM and c.get("state") == "off" for c in guard_if["if"]
    ), "snapshot must be guarded by the claim being unheld"
    then = guard_if["then"]
    assert steps_of(then) == ["scene.create", "input_boolean.turn_on"], (
        f"guarded block must snapshot then claim, got {steps_of(then)}"
    )
    assert sorted(then[0]["data"]["snapshot_entities"]) == sorted(PANELS), (
        "snapshot must cover both panels or the restore silently drops one"
    )

    turn_on = next(s for s in seq if s.get("action") == "light.turn_on")
    assert turn_on["data"]["brightness_pct"] == BRIGHTNESS_PCT, (
        f"expected {BRIGHTNESS_PCT}%, got {turn_on['data']['brightness_pct']}%"
    )
    assert sorted(turn_on["target"]["entity_id"]) == sorted(PANELS)
    assert f"({BRIGHTNESS_PCT}%" in auto["alias"], (
        f"alias still advertises a different brightness: {auto['alias']!r}"
    )

    # Brightness and colour must ship in ONE call. Measured 2026-08-08: a separate
    # adaptive_lighting.apply overrode brightness to 254 even with adapt_brightness
    # false, which is why the panels came up at full instead of 50%.
    assert not any(s.get("action") == "adaptive_lighting.apply" for s in seq), (
        "adaptive_lighting.apply overrides brightness even with adapt_brightness: false "
        "(AL 1.30.1) — read AL's colour off its switch attribute in the same light.turn_on "
        "instead, so brightness and colour are atomic"
    )
    assert len([s for s in seq if s.get("action") == "light.turn_on"]) == 1, (
        "exactly one light.turn_on: a second call can land between and override"
    )
    assert "color_temp_kelvin" in turn_on["data"], (
        "the turn_on must carry the colour too, or Adaptive Lighting never sets it"
    )
    # The colour must still come FROM Adaptive Lighting, not be hardcoded...
    ct_src = str(turn_on["data"]["color_temp_kelvin"])
    assert "adaptive_lighting" in ct_src, (
        "color_temp_kelvin must be templated off an Adaptive Lighting switch, got "
        f"{ct_src!r}"
    )
    # ...and specifically from the instance scoped to these panels. The Whole House
    # instance bottoms out at 2500 K because it is tuned for outdoor downlights, so it
    # can never reach the warm end these NL22 panels (1200-6500 K) actually support.
    assert AL_SWITCH in ct_src, (
        f"colour must come from {AL_SWITCH} (1800-6500 K, scoped to these panels), not "
        f"another instance: {ct_src!r}"
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
    assert tail_actions.index("input_boolean.turn_off") < tail_actions.index("scene.turn_on"), (
        "claim must be released before scene.turn_on, otherwise the scene switching a "
        "panel off re-enters panels_went_off and races the claim"
    )
    assert seq.index(turn_on) < delay_i, "lights must be driven before the delay, not after"

    # --- the stair-light automation must stay independent ------------------
    stairs = by_id.get("stairs_pir_motion_light")
    assert stairs is not None, "stairs_pir_motion_light disappeared"
    dumped = yaml.dump(stairs)
    for panel in PANELS:
        assert panel not in dumped, f"{panel} leaked into stairs_pir_motion_light"

    # --- no dangling Nanoleaf Elements entity ------------------------------
    for path in sorted(glob.glob(os.path.join(REPO, "automations", "*.yaml"))):
        with open(path) as fh:
            body = fh.read()
        assert "light.elements_b3cd_2" not in body, (
            f"{os.path.basename(path)} still references light.elements_b3cd_2"
        )

    check_stairs_light(by_id)
    check_boundary_is_complementary(by_id)

    print("stairs PIR automations (both): all invariants OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
