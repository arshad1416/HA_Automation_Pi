#!/usr/bin/env python3
"""Invariant check for the hallway_panels_stairs_pir automation.

These failure modes stay silent in HA — a wrong mode or a missing guard does not
raise, it just leaves the hallway panels burning at full brightness all night.
That is not hypothetical: the first version of this automation waited for
binary_sensor.pir_motion_sensor_2_motion to report 'off', which that sensor never
does (battery Tuya PIR: it pulses 'on' and sleeps to 'unavailable'). The panels
stayed lit until someone noticed. Several assertions below exist to pin that.

Run from anywhere:  python3 verification/test_hallway_panels_stairs_pir.py
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


def main():
    autos = load_automations()
    by_id = {a.get("id"): a for a in autos}
    auto = by_id.get("hallway_panels_stairs_pir")
    assert auto is not None, "automation hallway_panels_stairs_pir is missing"

    # --- THE regression guard -------------------------------------------
    # The sensor never reports 'off'. Any trigger waiting for it to do so is dead
    # code, and if it is the only restore path the panels never come back down.
    for trig in auto["triggers"]:
        ents = trig.get("entity_id")
        ents = [ents] if isinstance(ents, str) else (ents or [])
        if PIR in ents:
            assert trig.get("to") != "off", (
                f"trigger {trig.get('id')!r} waits for {PIR} to report 'off'. That sensor "
                "is a battery Tuya PIR that only ever pulses 'on' and sleeps to "
                "'unavailable' — this trigger can never fire, which is the exact bug "
                "that left the panels stuck at full brightness."
            )

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

    al = next(s for s in seq if s.get("action") == "adaptive_lighting.apply")
    assert al["data"]["adapt_color"] is True, "AL must set the colour — that is the point"
    assert al["data"]["adapt_brightness"] is False, (
        "adapt_brightness must be False or AL walks back the brightness above"
    )
    assert sorted(al["data"]["lights"]) == sorted(PANELS)

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
    assert al is not None and seq.index(turn_on) < delay_i, (
        "lights must be driven before the delay, not after"
    )

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

    print("hallway_panels_stairs_pir: all invariants OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
