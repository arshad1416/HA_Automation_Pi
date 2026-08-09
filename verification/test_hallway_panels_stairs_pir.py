#!/usr/bin/env python3
"""Invariant check for the hallway_panels_stairs_pir automation.

These are the failure modes that stay silent in HA — a wrong branch order or a
missing release branch does not raise, it just restores lights over someone's
deliberate turn-off at 2am. Run from anywhere:  python3 verification/test_hallway_panels_stairs_pir.py
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
# Brightness the PIR branch drives the panels to. Changing this must also change
# the automation's alias, which advertises the value to the user.
BRIGHTNESS_PCT = 50


def load_automations():
    out = []
    for path in sorted(glob.glob(os.path.join(REPO, "automations", "*.yaml"))):
        with open(path) as fh:
            for doc in yaml.load_all(fh, Loader=HALoader):
                if isinstance(doc, list):
                    out += [a for a in doc if isinstance(a, dict)]
    return out


def branch_for(auto, trigger_id):
    """The choose branch keyed on a given trigger id."""
    for option in auto["actions"][0]["choose"]:
        for cond in option["conditions"]:
            if cond.get("condition") == "trigger" and cond.get("id") == trigger_id:
                return option
    raise AssertionError(f"no choose branch for trigger id {trigger_id!r}")


def action_names(seq):
    return [step.get("action") for step in seq]


def main():
    autos = load_automations()
    by_id = {a.get("id"): a for a in autos}

    auto = by_id.get("hallway_panels_stairs_pir")
    assert auto is not None, "automation hallway_panels_stairs_pir is missing"

    # --- triggers -------------------------------------------------------
    trigger_ids = {t.get("id") for t in auto["triggers"]}
    assert trigger_ids == {"motion", "no_motion", "panels_went_off"}, (
        f"unexpected trigger ids: {trigger_ids}"
    )

    # The release trigger must watch BOTH panels, else a manual turn-off of the
    # unwatched one leaves the claim set and the timer restores over it.
    release = next(t for t in auto["triggers"] if t.get("id") == "panels_went_off")
    assert sorted(release["entity_id"]) == sorted(PANELS), (
        f"panels_went_off must watch both panels, got {release['entity_id']}"
    )
    assert release.get("to") == "off"

    no_motion = next(t for t in auto["triggers"] if t.get("id") == "no_motion")
    assert no_motion["entity_id"] == "binary_sensor.pir_motion_sensor_2_motion"
    assert no_motion["for"] == {"minutes": 5}, f"expected 5 min, got {no_motion['for']}"

    # --- restore branch: claim released BEFORE the scene replay ---------
    restore = branch_for(auto, "no_motion")
    names = action_names(restore["sequence"])
    assert "input_boolean.turn_off" in names and "scene.turn_on" in names
    assert names.index("input_boolean.turn_off") < names.index("scene.turn_on"), (
        "claim must be released before scene.turn_on, otherwise the scene switching a "
        "panel off re-enters panels_went_off and races the claim"
    )
    # Restore only runs while we actually hold the panels.
    assert any(
        c.get("entity_id") == "input_boolean.hallway_panels_pir_owned"
        and c.get("state") == "on"
        for c in restore["conditions"]
    ), "restore branch must require the claim to be held"

    # --- release branch exists and only drops the claim ------------------
    went_off = branch_for(auto, "panels_went_off")
    assert action_names(went_off["sequence"]) == ["input_boolean.turn_off"], (
        "the release branch must only drop the claim — anything else fights manual control"
    )

    # --- motion branch ---------------------------------------------------
    motion = branch_for(auto, "motion")
    conds = motion["conditions"]
    assert any(
        c.get("entity_id") == "sun.sun" and c.get("state") == "below_horizon"
        for c in conds
    ), "motion branch must be gated on sunset"
    # Guard against re-triggering mid-window overwriting the snapshot with our own state.
    assert any(
        c.get("entity_id") == "input_boolean.hallway_panels_pir_owned"
        and c.get("state") == "off"
        for c in conds
    ), "motion branch must skip when the claim is already held, or the snapshot is lost"

    seq = motion["sequence"]
    names = action_names(seq)
    assert names.index("scene.create") == 0, "snapshot must be taken before anything changes"

    snap = seq[0]["data"]
    assert sorted(snap["snapshot_entities"]) == sorted(PANELS), (
        "snapshot must cover both panels or the restore silently drops one"
    )

    turn_on = next(s for s in seq if s.get("action") == "light.turn_on")
    assert turn_on["data"]["brightness_pct"] == BRIGHTNESS_PCT, (
        f"expected {BRIGHTNESS_PCT}% brightness, got {turn_on['data']['brightness_pct']}%"
    )
    # The alias is user-visible and goes stale silently when the value changes.
    assert f"({BRIGHTNESS_PCT}%" in auto["alias"], (
        f"alias still advertises a different brightness: {auto['alias']!r}"
    )
    assert sorted(turn_on["target"]["entity_id"]) == sorted(PANELS)

    al = next(s for s in seq if s.get("action") == "adaptive_lighting.apply")
    assert al["data"]["adapt_color"] is True, "AL must set the colour — that is the point"
    assert al["data"]["adapt_brightness"] is False, (
        "adapt_brightness must be False or AL walks back the 100% brightness"
    )
    assert sorted(al["data"]["lights"]) == sorted(PANELS)
    # apply() only reads settings off this switch; membership is not required.
    assert al["data"]["entity_id"].startswith("switch.")

    # --- the stair-light automation must stay independent ----------------
    stairs = by_id.get("stairs_pir_motion_light")
    assert stairs is not None, "stairs_pir_motion_light disappeared"
    stairs_lights = yaml.dump(stairs)
    for panel in PANELS:
        assert panel not in stairs_lights, (
            f"{panel} leaked into stairs_pir_motion_light — the two automations must not "
            "both drive the panels"
        )

    # --- no dangling Nanoleaf Elements entity ----------------------------
    for path in sorted(glob.glob(os.path.join(REPO, "automations", "*.yaml"))):
        with open(path) as fh:
            body = fh.read()
        assert "light.elements_b3cd_2" not in body, (
            f"{os.path.basename(path)} still references light.elements_b3cd_2, "
            "which is not in the entity registry"
        )

    print("hallway_panels_stairs_pir: all invariants OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
