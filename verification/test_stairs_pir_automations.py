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
# The owner's after-sunset resting state for this hallway, set from the Nanoleaf app
# and read back from HA: white (hs 0,0) at 10%. The revert is this FIXED target, not a
# snapshot — deterministic and self-healing if the panels drift.
REVERT_PCT = 10
REVERT_HS = [0, 0]
# motion brightness per period, dimmest when the house is asleep
PERIOD_PCT = {"after_bedtime": 10, "after_sunset": 50, "dark_day": 75}
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

    night = step["else"]
    assert [x.get("action") for x in night] == ["light.turn_on"], (
        f"night revert must turn the panels on, got {[x.get('action') for x in night]}"
    )
    d = night[0]["data"]
    assert d.get("brightness_pct") == REVERT_PCT, (
        f"night resting brightness must be {REVERT_PCT}%, got {d.get('brightness_pct')}"
    )
    # NOT effect: "night light" — that scene exists only on the LEFT panel. Asking the
    # right one for it returns HTTP 500, and the call fails having already changed the
    # left, leaving the pair mismatched. White is what both units accept.
    assert list(d.get("hs_color") or []) == REVERT_HS, (
        f"night resting look must be white hs {REVERT_HS}, got {d.get('hs_color')}"
    )
    assert "effect" not in d, (
        "no effect here: the panels carry different custom scenes, so any effect name "
        "errors on one of them"
    )
    assert "color_temp_kelvin" not in d, (
        "colour temp would leave the panels in colour_temp mode, not the hs white they rest in"
    )
    assert sorted(night[0]["target"]["entity_id"]) == sorted(PANELS)


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

    # Snapshot happens only when unclaimed, so repeat pulses cannot overwrite it
    # with our own 50% state (which would make "previous state" mean "50%").
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
    bri = str(turn_on["data"]["brightness_pct"])
    for period, pct in PERIOD_PCT.items():
        assert str(pct) in bri, f"motion brightness for {period} ({pct}%) missing from {bri!r}"
    # after_bedtime implies sun below horizon, so it MUST be tested first or the 50%
    # sunset leg would always win and the after-bedtime 10% would be unreachable.
    assert bri.index("after_bedtime") < bri.index("below_horizon"), (
        "after_bedtime must be tested before the plain sunset case, otherwise the "
        "after-bedtime 10% leg is dead code"
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
    assert seq.index(turn_on) < delay_i, "lights must be driven before the delay, not after"

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

    print("stairs PIR automations (both): all invariants OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
