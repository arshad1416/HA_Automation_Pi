# EV Charging Subsystem Audit — 2026-07-30

Scope: `configuration.yaml` (EV blocks), `automations/05_grizzl_e_charging.yaml`, `automations/06_enhancements.yaml`, `automations/08_ev_per_vehicle_cost_tracking.yaml`, `dashboards/ev-charging.yaml`, `grizzl_e_rates.json`, `verification/preflight.sh`, `reference/entities.md`, and the `.storage/` registries. HA 2026.6.3.

Every finding is tagged **[repo-confirmed]** (provable from files in this worktree) or **[needs live check]** (requires runtime state on the Pi; the exact check is given). File anchors are repo-relative.

Root `automations.yaml` is legacy and not loaded — nothing here is sourced from it. `custom_components/` is vendored HACS code; it is cited only as evidence, never as something to edit.

---

> ### Status — fixes applied in this worktree, nothing deployed
>
> Approved and written, validated by rendering the templates (not just YAML syntax); `verification/preflight.sh` passes, 14 files, 0 failures:
>
> | | Change | Files |
> |---|---|---|
> | **A2** | `grizzl_e_daemon.py` + `grizzl_e_ha_parser.sh` recovered from `2d783a2`; systemd unit captured | `grizzl_e_daemon.py`, `grizzl_e_ha_parser.sh`, `pi-config/grizzl-e-daemon.service` |
> | **A4** | VF9 session energy switched to `dien_nang_lay_tu_luoi_lan_cuoi`; kW no longer printed as W; VNĐ costs dropped from the summary | `automations/06_enhancements.yaml` |
> | **A5** | `Armed` + `Safe` added to the security allowlist — verified `Not locked` / `Open: Driver Door` still alert | `automations/06_enhancements.yaml` |
> | **A7** | Tire threshold converted to 2.21 bar; message now converts to PSI. Verified: 2.48 bar → no alert, 2.10 bar → all four | `automations/06_enhancements.yaml` |
> | **A14** | `cua_sau_trai` → `cua_sau_tai_xe` | `automations/06_enhancements.yaml` |
> | **A1** | `initial:` removed from all 8 EV `input_number`s and `input_text.ev_session_vehicle` | `configuration.yaml` |
> | **A3** | `ev_charging_efficiency` now divides by SoC **gain**, per detected vehicle. Renders 0.80 kWh/% (Ioniq 60→85%), 1.25 (VF9 40→56%), unavailable when undetected | `configuration.yaml` |
> | **A17** | Fixed-cost ceiling 100000 → 5000000 ¢; unattributed 100000 → 1000000 ¢ | `configuration.yaml` |
> | **D1** | `type: attribute` added to all 7 rows — verified zero remain | `dashboards/ev-charging.yaml` |
> | **D4** | `days_to_show: 365` added to both per-vehicle trend charts | `dashboards/ev-charging.yaml` |
>
> **Not applied** (not in the approved set): A6, A8–A13, A15, A16, A18–A24, D2, D3, D5–D8, all of E, L and T.
>
> ### DEPLOYED to the Pi — 2026-07-31 00:11 EDT
>
> Sequence run per `AGENTS.md`: preflight → stage → `check_config` (exit 0) → stop → registry patch → start → `check_config` → restart → smoke tests.
> **Smoke tests: 8 pass / 3 fail, byte-identical to the pre-deploy baseline** (the 3 are pre-existing and unrelated: Ollama version pin, an unpulled `qwen2.5:7b`, and conversation-agent naming). **Zero errors** in the HA log since restart, excluding pre-existing `emulated_hue` / `wyzeapi` noise. Grizzl-E daemon PID 2374 untouched throughout; state file writing normally.
>
> **A2 closed the dangerous way it needed to be:** `grizzl_e_daemon.py` is back at `/opt/homeassistant/grizzl_e_daemon.py`, so `grizzl-e-daemon.service`'s `ExecStart` now resolves. The unlinked-inode process is no longer a single point of failure — a crash or reboot will now restart cleanly instead of entering a permanent failure loop.
>
> ### ⚠️ One thing did NOT work as intended — tire pressure units
>
> The plan was an entity-registry unit override pinning the four tire sensors to psi. It was applied cleanly with HA stopped (4 entities, JSON round-trip verified, 1861 entities intact) — **and HA discarded it.** The registry was rewritten at 00:02:52, ~5 minutes after startup, with `unit_of_measurement` back to `None` and precision back to `2`. A hand-written `options.sensor.unit_of_measurement` does not survive; the supported path is the UI (which goes through `async_update_entity_options`), or the websocket API with a token.
>
> That mattered more than cosmetics: the automation had been changed to compare against `32` on the assumption states would be psi. With the override gone, states are bar (~2.4), `0 < 2.4 < 32` is true for every tire, and **the original A7 spam bug was briefly live**. Caught in post-deploy verification and fixed.
>
> **Resolution — the automation no longer depends on the registry at all.** It normalises each reading before comparing (real tire pressures are 1.7–3.1 bar / 25–45 psi, so anything under 6 is unambiguously bar) and always reports in PSI. Render-tested in both regimes: 2.48 bar → no alert, 2.10 bar → all four flagged, 36.0 psi → no alert, 30.5 psi → flagged, `unknown`/0 → no alert.
>
> **Still open, 4 UI clicks:** to make the tire entities *display* psi in the UI, history and dashboards, set it per entity — Settings → Devices & Services → VF9 BLIBS → each tire sensor → ⚙ → Unit of Measurement → psi. The alerting is already correct without this; it is a display preference now, not a correctness issue.
>
> ### Second deploy — 2026-07-31 08:52 EDT
>
> **A18 — fixed and verified.** `sensor.grizzl_e_total_cost` is now `state_class: total` ([configuration.yaml:675](configuration.yaml:675)). HA had logged `state class 'total_increasing' ... is impossible considering device class ('monetary')` once per start; **0 occurrences since the restart**. `total` is also semantically correct — the daemon can revise cumulative cost downward when `grizzl_e_history.json` is re-rolled, which `total_increasing` would misread as a meter reset.
>
> **VF9 "left open / unlocked" alerts — now gated at a sustained hour.** The Alexa announce previously fired the instant `canh_bao_an_ninh` went non-`Safe`, i.e. on every door opening and every unlock. `vf9_security_alarm_alert` now has two paths:
>
> - **Security STATUS** (`trang_thai_an_ninh`) — unchanged, immediate. Verified: `Alarm` / `Triggered` fire; `Armed` / `Disarmed` / `unavailable` do not.
> - **Security WARNING** (`canh_bao_an_ninh`) — template trigger with `for: "01:00:00"`. A *template* trigger rather than a state trigger with `for:`, because the warning **string mutates** as openings change (`Open: Driver Door` → `Open: Driver Door, Trunk`), which would restart a state-trigger timer on every change. The template stays true across those transitions, so the hour is continuous insecure time.
>
> The parked check sits **inside** the template rather than in `conditions:`, so the hour only accumulates while stationary. `api_mqtt.py` gates `Not locked` on gear-in-park but does **not** gate `Open: <doors/windows>` — without this, driving for an hour with a window down would have announced a security alert across the whole house. Verified: window down at 45 km/h → clock does not run; same window down at 0 km/h → it does; `unavailable` → no alert.
>
> **`vf9_door_open_when_parked` retired.** It watched 10 entities individually (4 doors, trunk, hood, 4 windows); `api_security_warning` already aggregates exactly those 10 — `api_mqtt.py` `door_map` includes Trunk and Hood, `window_map` the four windows — plus `Not locked`. Keeping both meant two phone pushes for one event. It was also broken independently (**A6**): after `delay: "01:00:00"` it re-checked `trigger.to_state.state`, a snapshot frozen at trigger time and therefore always still "open", so it alerted an hour later even if the door had been shut 59 minutes earlier. The replacement re-evaluates live state continuously, so closing the door genuinely cancels the alert. Recover with `git show HEAD:automations/06_enhancements.yaml`.
>
> Post-deploy: `check_config` exit 0, **0 errors** since restart excluding known noise, 0 unique-ID clashes, smoke tests **8/3 — unchanged from baseline**, all four deployed files hash-match the Mac, daemon PID 2374 still writing. Automation count 30 → 29.
>
> The Pi's sync cron will auto-commit and push all deployed files, including the recovered daemon, within 15 minutes.

## Executive summary

- **The per-vehicle cost subsystem loses all of its data on every HA restart.** All eight EV `input_number` helpers and `input_text.ev_session_vehicle` set `initial:`, which suppresses state restore. Lifetime cost/energy per vehicle, the fixed-cost accumulator, and the unattributed bucket all return to zero, and nothing anywhere restores them. This is the single highest-value fix in the report.
- **🔴 The Grizzl-E daemon is running from a deleted file and dies permanently at the next restart.** Confirmed on the Pi: PID 2374 has run since 2026-07-28, but `/opt/homeassistant/grizzl_e_daemon.py` no longer exists — it was removed by auto-sync commit `1e2cf44` on 2026-07-29 while the process was live. Linux keeps the unlinked inode alive, so telemetry still flows and nothing looks wrong. But `grizzl-e-daemon.service` has `Restart=always` pointing at that missing path, so the first crash, `systemctl restart`, or reboot puts it into a permanent restart-failure loop — silently, because the `command_line` sensors keep succeeding on a frozen state file. **Recovered in this worktree** (`grizzl_e_daemon.py`, `grizzl_e_ha_parser.sh`, and the previously-untracked [pi-config/grizzl-e-daemon.service](pi-config/grizzl-e-daemon.service)); the git blob is provably byte-identical to the running version. One `scp` to the Pi closes it — see A2.
- **`sensor.ev_charging_efficiency` is dimensionally wrong** — it divides session kWh by *absolute* SoC instead of SoC gain, so it publishes a number roughly 8x below the healthy band printed in its own `expected_range` attribute. Do not put it on a dashboard until the formula is fixed.
- **Four VF9 automations in `06_enhancements.yaml` are actively wrong**, not merely imperfect: tire pressure compares bar readings against a PSI threshold (always "low", fires on every MQTT push); the security allowlist omits `Armed` and `Safe`, so every lock and every door-close triggers a house-wide Echo announcement; the door-ajar re-check reads a frozen trigger snapshot, so it always fires; and "session" energy reads a never-reset lifetime accumulator.
- **The dashboard's Current Session card is broken by a schema mistake, not a data problem.** Seven rows use `attribute:`/`suffix:` without `type: attribute`, so Lovelace silently ignores them — three rows in the same card render the identical lifetime dollar figure under three different labels.
- **The History view labels five days of metered data as "Lifetime" directly above a hardcoded 20-month, 14,294 kWh modeled table** whose own rows sum to 14,296 / $1,100, not the stated 14,294 / $1,102.
- **Every charging session fires 3 push notifications, 5 for the VF9**, from four automations that all trigger off the same session-end edge and never coordinate. Targeting is split with no rule behind it — 21 uses of the OnePlus-only service against 14 of the both-phones group, so the second handset misses most EV alerts.
- **Zero HA labels exist in this installation** — `.storage/core.label_registry` does not exist and all 3002 `labels` arrays are empty. There is nothing to deduplicate on the label axis; the real work is creating labels for the first time and giving the IONIQ 6 device an area (it has none; the VF9 is in `outdoor`).
- **Only one genuine entity-name collision exists across all 186 vehicle entities** (two VF9 "Outside Temperature" sensors, both voice-exposed) and **one genuine duplicate entity** (`sensor.monthly_ev_charging_cost`, a zero-consumer passthrough). The VF9's apparently-redundant SOH / charging-power / range families are deliberate cross-checks — a dedupe pass must not touch them.

---

## A. Automation and cost-attribution correctness

This is where data integrity lives. Ordered high → low.

### A1. `initial:` on every EV helper defeats state restore — all per-vehicle totals reset to zero on restart
**[needs live check]** — [configuration.yaml:280](configuration.yaml:280)

All eight EV `input_number` helpers set `initial:` — [280](configuration.yaml:280), [288](configuration.yaml:288), [296](configuration.yaml:296), [304](configuration.yaml:304), [312](configuration.yaml:312), [320](configuration.yaml:320), [328](configuration.yaml:328), [336](configuration.yaml:336) — as does `input_text.ev_session_vehicle` at [configuration.yaml:434](configuration.yaml:434). In `input_number`/`input_text`, a configured `initial` short-circuits `async_added_to_hass` before `async_get_last_state()` is called, so RestoreState never runs. The author used the correct pattern one domain over: `counter.season_switch_summer` at [configuration.yaml:445](configuration.yaml:445) sets `initial: 0` **plus** `restore: true`.

**Failure scenario.** `input_number.ioniq_6_total_cost_cents` holds 42350 (~$423 lifetime). `docker restart homeassistant` → 0. Simultaneously `vf9_total_cost_cents`, both `*_total_energy_kwh`, `ev_fixed_cost_accumulated_cents` and `ev_unknown_cost_cents` zero out. The template sensors that read them — `sensor.ev_ioniq_6_total_cost`, `ev_vf9_total_cost`, `ev_*_total_energy`, `ev_fixed_cost_total` ([configuration.yaml:816-844](configuration.yaml:816)) — follow to 0, and the entire Per-Vehicle dashboard view resets permanently. There is no writer anywhere that could restore them. Downstream, on the 1st of the month [automations/08_ev_per_vehicle_cost_tracking.yaml:148](automations/08_ev_per_vehicle_cost_tracking.yaml:148) evaluates `total_variable > 0` as false and takes the `default:` branch, pushing "No variable costs recorded this month."

**Explicitly not a failure:** a mid-session restart does *not* cause vehicle misattribution. `binary_sensor.grizzl_e_charging` transitions `unknown → on` after the restart, which matches the bare `to: "on"` trigger at [automations/08_ev_per_vehicle_cost_tracking.yaml:24](automations/08_ev_per_vehicle_cost_tracking.yaml:24) and immediately re-writes both SoC baselines from current SoC ([08:29-38](automations/08_ev_per_vehicle_cost_tracking.yaml:29)). The realistic degradation is the opposite — post-restart gains are small, the detector returns `unknown`, and the session lands in the unattributed bucket. Also note a YAML *reload* of `input_number` does not re-apply `initial`; only a full restart does.

**Fix.** Delete every `initial:` key from the eight helpers and from `input_text.ev_session_vehicle`. Omitting it is what enables RestoreEntity (`.storage/core.restore_state` is already gitignored at [.gitignore:45](.gitignore:45)). Seed the accumulators once by hand via Developer Tools after the change. If a defined value is genuinely wanted on a true first boot, do it from an automation on `homeassistant_start` guarded by `states(...) in ['unknown','unavailable']`.

```yaml
  ioniq_6_total_cost_cents:
    name: "IONIQ 6 Total Cost (cents)"
    min: 0
    max: 1000000
    step: 1
    # initial: 0        <-- delete this line (and the same in the other 8 helpers)
    unit_of_measurement: "¢"
```

**Live check:** note `input_number.ioniq_6_total_cost_cents` in Developer Tools → States, restart HA, re-read it. If it reads 0, confirmed.

---

### A2. `grizzl_e_daemon.py` was deleted from the repo by auto-sync; its systemd unit and cumulative history were never tracked
**[repo-confirmed]** — [AGENTS.md:11](AGENTS.md:11)

> ## ⚠️ RESOLVED 2026-07-30 — case (b), the dangerous one. Diagnosed on the Pi with the user's approval.
>
> **The daemon is running from a file that no longer exists on disk. It is one crash away from being gone permanently.**
>
> Evidence, read-only over `ssh pi-lan`:
>
> ```
> $ pgrep -af grizzl_e_daemon
> 2374 /usr/bin/python3 /opt/homeassistant/grizzl_e_daemon.py 192.168.0.115 ...
>
> $ ls -l /opt/homeassistant/grizzl_e_daemon.py
> ls: cannot access '...': No such file or directory
>
> $ ps -o lstart,etime -p 2374
> Tue Jul 28 01:53:10 2026   2-21:46:40
> ```
>
> PID 2374 started **2026-07-28 01:53**, before the 2026-07-29 19:02 deletion, and has run continuously since. Linux keeps an unlinked inode alive for as long as a process holds it, so the daemon works normally — `grizzl_e_state.json` was written 11 seconds before the check — while its source is unrecoverable from the filesystem. `/proc/2374/fd` holds no deleted-file descriptor (CPython closes the script after compiling it), so **the running source cannot be recovered from the live process.**
>
> **What makes this urgent rather than merely untidy:** `/etc/systemd/system/grizzl-e-daemon.service` exists, is enabled, and specifies `Restart=always` with
> `ExecStart=/usr/bin/python3 /opt/homeassistant/grizzl_e_daemon.py …`. The moment PID 2374 exits — an unhandled exception on a network blip, `systemctl restart`, a reboot — systemd will relaunch it, `ExecStart` will fail with ENOENT, and it will enter a permanent restart-failure loop. EV telemetry stops with no notification, and the `command_line` sensors keep succeeding on `cat` of a frozen state file, so nothing in HA surfaces the failure.
>
> **The git blob is provably the running version.** `git log --all -- grizzl_e_daemon.py` shows exactly three commits: `4fc1df9` (2026-07-25 23:47), `2d783a2` (2026-07-26 00:17), `1e2cf44` (deletion, 2026-07-29 19:02). The last content change predates the 2026-07-28 process start, and the Pi's sync cron commits every 15 minutes, so any on-disk edit between those dates would have produced a commit. There is none. **`2d783a2:grizzl_e_daemon.py` is byte-identical to what PID 2374 loaded.**
>
> **Recovery is safe and does not disturb the running process** — restoring the file only repairs the restart path.
>
> Done in this worktree already: `grizzl_e_daemon.py` (292 lines, syntax-checked) and `grizzl_e_ha_parser.sh` (51 lines) restored from `2d783a2`; the systemd unit captured to [pi-config/grizzl-e-daemon.service](pi-config/grizzl-e-daemon.service), which had never been version-controlled.
>
> Still to do **on the Pi** (requires approval; single file copy, no restart, no `systemctl` call):
> ```bash
> scp grizzl_e_daemon.py grizzl_e_ha_parser.sh pi-lan:/opt/homeassistant/
> ```
>
> Root cause, for the record: the other five removals in `1e2cf44` were a coherent cleanup — `check_garage_vision.py` went out together with its `command_line` sensor and template `binary_sensor` in the same commit, `disabled_kitchen_consolidation.yaml` was already disabled, and `tuya_listener.py` / `update_kitchen_presence.py` are superseded by the surviving `tuya_kitchen_bridge.py`. `grizzl_e_daemon.py` and `grizzl_e_ha_parser.sh` are the only removals with **no** corresponding config change — all five Grizzl-E `command_line` sensors at [configuration.yaml:624-684](configuration.yaml:624) still read the file the daemon writes. They were swept up in a cleanup of genuinely dead files while not being dead, and because the process kept running, nothing surfaced the mistake.

The daemon *was* version-controlled: added in `4fc1df9`, modified in `2d783a2`, then **deleted in `1e2cf44`** (Auto-sync 2026-07-29 19:02:02). Because `git-sync.sh:49` runs `git add -A`, a file disappearing from `/opt/homeassistant` propagates as a deletion and is pushed within 15 minutes. The same commit deleted `check_garage_vision.py`, `tuya_listener.py`, `update_kitchen_presence.py` and `grizzl_e_ha_parser.sh` — four of the five root daemons [AGENTS.md:11](AGENTS.md:11) declares curated. Only `tuya_kitchen_bridge.py` survives. The daemon's own docstring says "Run via systemd (see grizzl-e-daemon.service)", and `git log --all -- '*grizzl*service*'` returns nothing — that unit has never existed in history. `grizzl_e_history.json`, the single store of cumulative EV energy/cost that the daemon seeds totals from (defaulting to `0.0`), is gitignored at [.gitignore:77](.gitignore:77) with no backup path.

**Failure scenario.** The Pi's SD card fails or the config is rebuilt from this repo. [configuration.yaml:624-684](configuration.yaml:624) defines five `command_line` sensors that all `cat /config/grizzl_e_state.json`; nothing in the repo can produce that file. Every EV entity goes unavailable, all sixteen utility_meters stall, all three dashboard views break, and the cumulative kWh/$ is unrecoverable. Recovery means reconstructing a 292-line daemon plus its service unit from scratch. This is not hypothetical — the deletion already happened once, unnoticed, via an automated push.

**Fix.** *(reordered after the 2026-07-30 update — diagnose before restoring)*
1. **First, find the live copy.** `ssh pi-lan 'pgrep -af grizzl_e_daemon; ls -l /proc/$(pgrep -f grizzl_e_daemon | head -1)/exe /proc/$(pgrep -f grizzl_e_daemon | head -1)/cwd'`. If `/proc/<pid>/` shows the script path with ` (deleted)` appended, that is case (b) — recover before anything restarts the process. `systemctl cat grizzl-e-daemon` reveals the configured path and settles (a) vs (b).
2. **Restore from the live file, not from git**, if the process is still readable: `cp /proc/<pid>/fd/... ` is unreliable for scripts, so prefer the systemd `ExecStart` path if it still exists; only fall back to `git show 2d783a2:grizzl_e_daemon.py > grizzl_e_daemon.py` (blob intact, 292 lines) if the live copy is unrecoverable — and diff the two before trusting either.
3. Commit the systemd unit as `pi-config/grizzl-e-daemon.service` (the repo already holds `pi-config/ollama-systemd-override.conf`, so the pattern exists).
4. Back up `grizzl_e_history.json` to a tracked location or an off-Pi target.
5. Reconcile [AGENTS.md:11](AGENTS.md:11) with reality for all five daemons.

Note the user created `sensor.ev_ioniq_6_total_cost` on 2026-07-31T01:08Z per the entity registry — i.e. is still building on this pipeline two days after its producer left `/config`. Data is presumably still flowing (the daemon is running from somewhere), which is why this is high rather than critical; confirm with `ssh pi 'ls -l /opt/homeassistant/grizzl_e_state.json; pgrep -af grizzl_e_daemon'`.

---

### A3. `sensor.ev_charging_efficiency` divides by absolute SoC, not SoC gain — the unit and the documented healthy range are both false
**[repo-confirmed]** — [configuration.yaml:772](configuration.yaml:772)

State is `session_kwh / (soc * 0.01 * 77.4)` where `soc` ([configuration.yaml:771](configuration.yaml:771)) is the IONIQ's *current absolute* SoC. `soc * 0.01 * 77.4` is the energy currently sitting in the pack, so the expression is a dimensionless ratio (session energy ÷ pack contents), not kWh per percent. It coincides with true kWh/% only when the session started at 0%. It also keys exclusively on `sensor.ioniq_6_ev_battery_level`, so it reports IONIQ-labelled numbers when the VF9 is on the charger.

**Failure scenario.** IONIQ tops up 60% → 70%, drawing 7.74 kWh. True efficiency is 7.74/10 = 0.774 kWh/%, dead centre of the healthy band. The sensor computes 7.74 / (70 × 0.774) = **0.143** and publishes it as "kWh/%" next to an `expected_range` attribute reading `0.74-0.80 kWh/% when healthy` ([configuration.yaml:775](configuration.yaml:775)) — an apparent 82% efficiency collapse on a perfectly healthy pack. A 95→100% top-up reads 0.053. A VF9 session of 20 kWh while the IONIQ idles at 80% reports 0.323 as an IONIQ figure.

**Fix.** Compute against the SoC delta, reusing the baseline helper the detection sensor already maintains, and gate availability so it goes unavailable rather than lying during VF9 sessions:

```yaml
      - name: "EV Charging Efficiency"
        unique_id: ev_charging_efficiency
        unit_of_measurement: "kWh/%"
        availability: >
          {{ states('sensor.ev_charging_vehicle_detected') == 'ioniq_6'
             and (states('sensor.ioniq_6_ev_battery_level') | float(0)
                  - states('input_number.ev_session_soc_start_ioniq') | float(0)) > 0.1 }}
        state: >
          {% set session_kwh = state_attr('sensor.grizzl_e_total_cost', 'session_energy_kwh') | default(0, true) | float(0) %}
          {% set gain = states('sensor.ioniq_6_ev_battery_level') | float(0)
                        - states('input_number.ev_session_soc_start_ioniq') | float(0) %}
          {{ (session_kwh / gain) | round(3) }}
```

(The existing availability gate at [configuration.yaml:766-768](configuration.yaml:766) tests `session_energy_kwh > 1`, a daemon attribute whose post-session behaviour is not verifiable from this repo — the dimensional bug stands regardless.)

---

### A4. VF9 "session" energy reads a lifetime cumulative accumulator
**[repo-confirmed]** — [automations/06_enhancements.yaml:397](automations/06_enhancements.yaml:397)

`ev_vf9_soc_energy_reconciliation` sets `kwh_delivered` from `sensor.vf9_rllv2cja5rh000847_dien_nang_sac_tai_nha` and treats it as this session's energy: [line 399](automations/06_enhancements.yaml:399) computes `expected_soc_gain = kwh_delivered / 1.23`, [line 402](automations/06_enhancements.yaml:402) gates on `kwh_delivered > 2`, [line 408](automations/06_enhancements.yaml:408) prints "Session: {{ kwh_delivered }} kWh delivered". That entity is "Home Charging Energy" (`api_home_charge_kwh`), which the integration accumulates forever and never resets (`custom_components/vinfast/api_mqtt.py:614` adds to the prior value). The same mistake recurs at [line 1015](automations/06_enhancements.yaml:1015) (`vf9_charging_session_summary`) and [line 1171](automations/06_enhancements.yaml:1171) (weekly summary — see A16).

The correct per-session entity already exists and is unused: `sensor.vf9_rllv2cja5rh000847_dien_nang_lay_tu_luoi_lan_cuoi` ("Grid Energy Drawn (Last)", kWh).

**Failure scenario.** After 40 home sessions the VF9 has accumulated 500 kWh. The 41st adds 12 kWh. At session end [line 397](automations/06_enhancements.yaml:397) reads 512, [line 399](automations/06_enhancements.yaml:399) computes 512 / 1.23 = 416.3, and the push reads "Session: 512.0 kWh delivered. Expected ~416.3% SoC gain (123 kWh pack). Current SoC: 78.0%." The `> 2` gate is permanently satisfied after the first session ever, so this fires on every session end forever and the reconciliation can never detect a real energy/SoC mismatch.

**Fix.** Replace the entity at [397](automations/06_enhancements.yaml:397) and [1015](automations/06_enhancements.yaml:1015):

```yaml
        kwh_delivered: "{{ states('sensor.vf9_rllv2cja5rh000847_dien_nang_lay_tu_luoi_lan_cuoi') | default(0, true) | float(0) }}"
```

Also fix the unit bug in the same automation: [line 1016](automations/06_enhancements.yaml:1016) reads `..._cong_suat_sac_trung_binh_lan_cuoi`, whose registry unit is **kW**, but [line 1026](automations/06_enhancements.yaml:1026) prints `{{ avg_power | round(0) }} W` — a 6.6 kW session renders as "7 W". Change to `kW` and `| round(1)`.

---

### A5. VF9 security alert allowlist omits "Armed" and "Safe" — house-wide Echo announcement on every lock and every door close
**[repo-confirmed]** — [automations/06_enhancements.yaml:874](automations/06_enhancements.yaml:874)

`vf9_security_alarm_alert` ([858-885](automations/06_enhancements.yaml:858)) triggers on any state change of two sensors and fires unless the new state is in the allowlist at [line 874](automations/06_enhancements.yaml:874): `['unknown','unavailable','none','','Normal','normal','Disarmed','disarmed','Off','off','None']`. Neither sensor ever emits "Normal". Two real normal-operation strings are missing:

- `sensor.vf9_..._trang_thai_an_ninh` ("Security Status") emits only **"Armed"** or **"Disarmed"** (`custom_components/vinfast/sensor.py:98-101`). "Disarmed" is excluded; **"Armed" is not**.
- `sensor.vf9_..._canh_bao_an_ninh` ("Security Warning") emits **"Safe"** whenever the warnings list is empty (`api.py:67`, `api_mqtt.py:667-670`), otherwise a joined string like `"Open: Driver Door | Not locked"`. **"Safe" is not in the allowlist.**

The actions ([876-885](automations/06_enhancements.yaml:876)) send a push *and* `notify.alexa_media` with `type: announce` to `media_player.everywhere`.

**Failure scenario.** You lock the VF9 on the way out. `trang_thai_an_ninh` goes Disarmed → "Armed", passes the filter, and every Echo in the house announces "Security alert. The VinFast VF9 security status has changed to Armed. Please check the vehicle immediately." Separately, closing the driver door sends `canh_bao_an_ninh` from "Open: Driver Door" → "Safe", which also passes, producing a second whole-home announcement. Every routine lock/unlock and door cycle produces a false critical alert.

**Fix.** Split the intent rather than patching the allowlist. Alert only on `canh_bao_an_ninh` becoming something other than `Safe`, and drop `trang_thai_an_ninh` entirely (Armed/Disarmed is lock state, not an alarm):

```yaml
  triggers:
    - trigger: state
      entity_id: sensor.vf9_rllv2cja5rh000847_canh_bao_an_ninh
  conditions:
    - condition: template
      value_template: >
        {{ trigger.to_state.state not in
           ['Safe','safe','unknown','unavailable','none','','None'] }}
```

Consider dropping `media_player.everywhere` to a single Echo until the state values are confirmed live.

---

### A6. VF9 door-open re-check after the 60-minute delay reads a frozen trigger snapshot — always fires
**[repo-confirmed]** — [automations/06_enhancements.yaml:934](automations/06_enhancements.yaml:934)

`vf9_door_open_when_parked` ([888-938](automations/06_enhancements.yaml:888)) delays one hour ([line 932](automations/06_enhancements.yaml:932)) then re-checks with `value_template: "{{ trigger.to_state.state | lower in ['open','on','mo'] }}"`. `trigger.to_state` is the state object captured **at trigger time** — a frozen snapshot that does not track the entity. Since the entry condition at [line 928](automations/06_enhancements.yaml:928) already required that same snapshot to be open-ish, the re-check is a tautology. The correct idiom is already used three times in this same file — [164](automations/06_enhancements.yaml:164), [190](automations/06_enhancements.yaml:190), [195](automations/06_enhancements.yaml:195) all use `{{ is_state(trigger.entity_id, 'on') }}`.

**Failure scenario.** You open the VF9 driver door in the driveway, grab a bag, close it 10 seconds later. Sixty minutes on, the condition evaluates the frozen 'Open' snapshot as true and pushes "Driver Door has been open for 60 min while parked." With `mode: parallel, max: 10` ([893-894](automations/06_enhancements.yaml:893)), ten triggering entities and no `to:` filter, a normal errand (open driver door, open trunk, close both) queues **two** independent runs, each producing a false alert an hour later.

**Fix.**

```yaml
    - condition: template
      value_template: "{{ states(trigger.entity_id) | lower in ['open','on','mo'] }}"
```

Better still, replace the delay-then-check with `for: "01:00:00"` plus explicit `to:` values on the state triggers, which removes the parallel-run pileup entirely.

---

### A7. VF9 tire-pressure alert compares bar readings against a PSI threshold — permanently "low", fires on every MQTT update
**[repo-confirmed]** — [automations/06_enhancements.yaml:846](automations/06_enhancements.yaml:846)

`vf9_tire_pressure_alert` ([817-855](automations/06_enhancements.yaml:817)) builds `low_list` with `0 < fl < 32` / `fr` / `rl` / `rr` ([846-849](automations/06_enhancements.yaml:846)) and the message at [line 855](automations/06_enhancements.yaml:855) says "below 32 PSI". The four VF9 tire sensors are natively in **bar** — the entity registry records `bar` as the unit with no override, and `custom_components/vinfast/const_vf8.py:31-34` declares all four as `("... Tire Pressure", "bar", ...)` (`const_vf9.py:3` copies `BASE_SENSORS`). No `psi` string appears anywhere in the integration. A correctly inflated VF9 tire reads ~2.4-2.8 bar (35-41 PSI), so `0 < 2.4 < 32` is true for all four tires at all times. There is no `to:` filter and no `for:` on any of the four state triggers ([824-835](automations/06_enhancements.yaml:824)), and the vinfast integration is MQTT-push driven.

**Failure scenario.** The VF9 is driven with all four tires correctly inflated at 2.5 bar. Every MQTT tire message fires the automation; the condition at [line 850](automations/06_enhancements.yaml:850) is always satisfied; `notify.mobile_app_cph2655` sends "Front-Left, Front-Right, Rear-Left, Rear-Right tires are below 32 PSI. Values: FL=2.5, FR=2.5, RL=2.5, RR=2.5." repeatedly for the whole drive. `mode: single` does not throttle it because the action sequence has no delay and completes in milliseconds. Conversely a genuinely flat tire at 1.4 bar is indistinguishable from a healthy one — the alert conveys nothing.

**Fix.** Convert the threshold to bar (32 PSI = 2.206 bar) and fix the message text:

```yaml
        {{ (['Front-Left'] if 0 < fl < 2.2 else []) +
           (['Front-Right'] if 0 < fr < 2.2 else []) + ... }}
```

Add `for: "00:02:00"` to the four state triggers and an `input_boolean` latch (or a stored last-alert timestamp) so a real low-pressure condition notifies once, not on every push.

**Live confirmation of the unit** (the unit/threshold mismatch is repo-provable; the live magnitude is not): Developer Tools → Template → `{{ state_attr('sensor.vf9_rllv2cja5rh000847_ap_suat_lop_truoc_trai','unit_of_measurement') }}`

---

### A8. Session-end detection fires 2 minutes after charging stops, far shorter than the IONIQ's cloud refresh — and the no-force-refresh window is exactly the overnight rate window
**[needs live check]** — [automations/08_ev_per_vehicle_cost_tracking.yaml:57](automations/08_ev_per_vehicle_cost_tracking.yaml:57)

Attribution runs 2 minutes after `binary_sensor.grizzl_e_charging` goes off and needs both vehicles' SoC to have already refreshed. kia_uvo defaults are `DEFAULT_SCAN_INTERVAL = 30` minutes and `DEFAULT_FORCE_REFRESH_INTERVAL = 1440` minutes (`custom_components/kia_uvo/const.py:39-40`), and the coordinator only issues a force-refresh **outside 22:00–07:00** (`const.py:41-42`, gate at `coordinator.py:160-172`) — inside that window it uses Hyundai's server-side cache. [grizzl_e_rates.json:13](grizzl_e_rates.json:13) puts the ULO overnight rate at 23:00–07:00, entirely inside that blackout. The hours the tariff financially steers you into are precisely the hours the IONIQ is never woken. The VF9 by contrast is MQTT push, so the two vehicles' freshness is wildly asymmetric.

**Failure scenario.** IONIQ charges 23:30 → 05:00 overnight. At 05:02 the automation reads `sensor.ioniq_6_ev_battery_level`, still the cached pre-session value, so `ioniq_gain ≈ 0`. Best case [configuration.yaml:800](configuration.yaml:800) returns `unknown` and the whole overnight cost lands in `input_number.ev_unknown_cost_cents`. Worse: the push-driven VF9 reports any >1% rise in that window (preconditioning, a stale-then-corrected reading) and [configuration.yaml:790](configuration.yaml:790) bills the IONIQ's entire overnight session to the VF9. The same `> 1` deadband also swallows small sessions — with integer-percent reporting, `gain > 1` means gain ≥ 2%, i.e. ≥1.55 kWh (IONIQ) or ≥2.46 kWh (VF9); anything smaller is `unknown`. A negative gain (car driven between baseline and read) fails all branches identically.

**Fix.** Do not attribute on a timer. Force a refresh and wait for the value to move:

```yaml
  actions:
    - action: button.press
      target: {entity_id: button.ioniq_6_force_refresh}
    - wait_template: "{{ states('sensor.ioniq_6_ev_battery_level') | float(0) > states('input_number.ev_session_soc_start_ioniq') | float(0) }}"
      timeout: "00:10:00"
      continue_on_timeout: true
```

Failing that, extend to `for: "00:35:00"` so at least one kia_uvo poll has elapsed. Separately loosen the deadband from `> 1` to `>= 1` at [configuration.yaml:788](configuration.yaml:788)/[790](configuration.yaml:790) and add an explicit negative-gain branch so a drive-away cannot fall through to a spurious single-vehicle match.

**Live check:** `docker exec homeassistant python -c "import json;d=json.load(open('/config/.storage/core.config_entries'));[print(e['domain'],e.get('options')) for e in d['data']['entries'] if e['domain']=='kia_uvo']"` — `.storage/core.config_entries` is gitignored, so the actual configured interval is unproven from here. Cross-check the IONIQ SoC sensor's `last_changed` against a known overnight session.

---

### A9. Monthly reconciliation divides lifetime accumulators it describes as "this month", and persists no per-vehicle split at all
**[repo-confirmed]** — [automations/08_ev_per_vehicle_cost_tracking.yaml:146](automations/08_ev_per_vehicle_cost_tracking.yaml:146)

`ioniq_cost` and `vf9_cost` at [146-147](automations/08_ev_per_vehicle_cost_tracking.yaml:146) read `input_number.*_total_cost_cents`, which are **lifetime** accumulators — a repo-wide grep confirms their only writers are the additive session-end handlers at [08:74](automations/08_ev_per_vehicle_cost_tracking.yaml:74) and [08:98](automations/08_ev_per_vehicle_cost_tracking.yaml:98), and nothing anywhere resets them monthly, daily, or on any schedule. The header at [08:14](automations/08_ev_per_vehicle_cost_tracking.yaml:14) nonetheless calls this a split "based on each vehicle's variable cost share", and the default branch at [08:171](automations/08_ev_per_vehicle_cost_tracking.yaml:171) says "this month". Separately, the proportional split exists **only as text inside the notification body** at [164-166](automations/08_ev_per_vehicle_cost_tracking.yaml:164) — the only state written is a flat `+3357` to `input_number.ev_fixed_cost_accumulated_cents` at [line 159](automations/08_ev_per_vehicle_cost_tracking.yaml:159).

**Failure scenario.** Month 1: IONIQ spends $100, VF9 $0 → push says "IONIQ $33.57, VF9 $0.00". Month 2: VF9 spends $100, IONIQ $0 → lifetime totals are now $100/$100, so the push says "IONIQ $16.79, VF9 $16.79". The month-2 split is wrong for both cars, and by month N the ratio converges to the all-time average and stops responding to monthly usage entirely. Nothing is stored, so the push is the only record — dismiss it and the allocation is gone, and `sensor.ev_fixed_cost_total` ([configuration.yaml:844](configuration.yaml:844)) shows an unsplittable lump.

**Fix.** Add `input_number.ioniq_6_fixed_cost_cents` and `input_number.vf9_fixed_cost_cents` and write the split to them instead of only rendering it. Compute the ratio from the per-vehicle **monthly** utility_meters that already exist ([configuration.yaml:919](configuration.yaml:919), [925](configuration.yaml:925)) — but read their `last_period` attribute, not their state: at 00:01 on the 1st those meters have already rolled over to zero.

```yaml
        ioniq_month: "{{ state_attr('sensor.ioniq_6_cost_monthly','last_period') | float(0) }}"
        vf9_month:   "{{ state_attr('sensor.vf9_cost_monthly','last_period') | float(0) }}"
```

---

### A10. The baseline recorder rewrites SoC baselines on every charger "on" edge, so a mid-session pause destroys the session's own attribution
**[needs live check]** — [automations/08_ev_per_vehicle_cost_tracking.yaml:27](automations/08_ev_per_vehicle_cost_tracking.yaml:27)

`ev_session_start_record_soc` triggers unconditionally on `binary_sensor.grizzl_e_charging → on` ([24-27](automations/08_ev_per_vehicle_cost_tracking.yaml:24)) with no guard against a session already in progress. The end handler fires on `off` held for only 2 minutes ([53-57](automations/08_ev_per_vehicle_cost_tracking.yaml:53)).

**Failure scenario.** IONIQ charges 22:00 → 02:00. The EVSE drops out for 4 minutes at 00:30 (GFCI self-test retry, brownout, or a car-side scheduled pause). At 00:32 the end handler runs and attributes the partial session; at 00:34 charging resumes and the start handler overwrites both baselines with the *current mid-charge* SoC. At 02:02 the real end sees only the 00:34→02:00 tail — if that tail is ≤1% the detector returns `unknown` ([configuration.yaml:800](configuration.yaml:800)) and the default branch at [08:122](automations/08_ev_per_vehicle_cost_tracking.yaml:122) overwrites `input_text.ev_session_vehicle` from the correct `ioniq_6` back to `unknown` while pushing a false "Vehicle Not Detected" alert.

**Fix.** Guard the start handler and have the end handler clear the guard:

```yaml
  conditions:
    - condition: not
      conditions:
        - condition: state
          entity_id: input_text.ev_session_vehicle
          state: "detecting"
```

Lengthen the `off` debounce at [08:57](automations/08_ev_per_vehicle_cost_tracking.yaml:57) well past typical EVSE dropout. Whether the daemon's `session_cost_cents` also double-counts across a pause is not provable from this repo (`grizzl_e_daemon.py` is absent) — check `ssh pi 'cat /opt/homeassistant/grizzl_e_state.json'` before and after a pause.

**Live check for reachability:** Developer Tools → History on `binary_sensor.grizzl_e_charging` over a known overnight charge; look for multiple on/off edges inside one plug-in period.

---

### A11. An IONIQ-only reconciliation duplicates automation 08's trigger and reports the wrong car's data
**[repo-confirmed]** — [automations/06_enhancements.yaml:358](automations/06_enhancements.yaml:358)

`ev_soc_energy_reconciliation` ([352-380](automations/06_enhancements.yaml:352)) triggers on `binary_sensor.grizzl_e_charging`, `from: 'on'`, `to: 'off'`, `for: "00:02:00"` ([359-363](automations/06_enhancements.yaml:359)). `ev_session_end_attribute_cost` at [08:53-57](automations/08_ev_per_vehicle_cost_tracking.yaml:53) fires on the same on→off transition (it simply omits the `from:`). File 08 exists specifically to identify *which* car was on the charger. The 06 copy performs no detection at all: [line 368](automations/06_enhancements.yaml:368) hardcodes `sensor.ioniq_6_ev_battery_level` and [line 369](automations/06_enhancements.yaml:369) hardcodes the IONIQ's `/ 0.774`. [configuration.yaml:942-946](configuration.yaml:942) shows `notify.grizzl_ev_phones` (used by 08) is a group containing `mobile_app_cph2655`, which is also the direct target of the 06 copy — so that handset gets both messages for the same event.

**Failure scenario.** The VF9 charges overnight drawing 30 kWh; the IONIQ is parked, unplugged, at 62%. Two minutes after the charger idles, 08 correctly sends "EV Session Complete — VF9 … 30.0 kWh", then 06 [line 374](automations/06_enhancements.yaml:374) sends to the same phone "EV Charging Reconciliation — Session: 30.0 kWh delivered. Expected ~38.8% SoC gain (77.4 kWh pack). Current SoC: 62.0%." — the VF9's energy divided by the IONIQ's pack constant, paired with the IONIQ's unrelated SoC. No stored state is corrupted (08 owns all `input_number` writes), but the user sees two contradictory session reports.

**Fix.** Delete [automations/06_enhancements.yaml:352-380](automations/06_enhancements.yaml:352). If the SoC-vs-energy sanity check is worth keeping, move it inside 08's `vehicle == 'ioniq_6'` branch ([08:66-88](automations/08_ev_per_vehicle_cost_tracking.yaml:66)) where the vehicle is already known, and use `input_number.ev_session_soc_start_ioniq` to report an actual delta instead of only the current SoC.

---

### A12. VF9 auto-lock notifies a service that probably does not exist, erroring on every departure
**[needs live check]** — [automations/06_enhancements.yaml:966](automations/06_enhancements.yaml:966)

*Repo-confirmed: `notify.sm_s926w` appears exactly once in the loaded config, while every other reference to this handset uses `mobile_app_sm_s926w`. Not repo-confirmable: whether the call resolves anyway. Recent HA versions register a notify **entity** named `notify.<device>` alongside the legacy `notify.mobile_app_<slug>` **service**, and those are different namespaces — an `action: notify.sm_s926w` call may or may not find a service depending on the mobile_app version. **Check:** Developer Tools → Actions → type `notify.sm_s926w`. If it does not autocomplete, the finding holds.*

`vf9_auto_lock_on_departure` ([941-969](automations/06_enhancements.yaml:941)) ends with `- action: notify.sm_s926w`. Mobile-app notify services are `notify.mobile_app_<slug>`. Every other reference to this handset in the loaded config uses the correct name — [configuration.yaml:946](configuration.yaml:946) and [automations/01_main.yaml:1350](automations/01_main.yaml:1350). A repo-wide grep finds `notify.sm_s926w` exactly once, so it is a typo, not a user alias.

**Failure scenario.** A phone leaves the home zone. The lock button press at [line 959](automations/06_enhancements.yaml:959) and the first notification at [962](automations/06_enhancements.yaml:962) both complete, then line 966 raises `Service notify.sm_s926w not found`. Larissa's handset — the whole reason the second notify exists — is never told the lock command was sent, and an error is logged on every departure by either person.

**Fix.** Replace both notify blocks ([962-969](automations/06_enhancements.yaml:962)) with a single `- action: notify.grizzl_ev_phones`, which already fans out to both handsets per [configuration.yaml:942-946](configuration.yaml:942).

---

### A13. Phantom-drain heuristic is inverted, and the VF9 branch has no location gate
**[needs live check]** — [automations/06_enhancements.yaml:436](automations/06_enhancements.yaml:436)

`ev_phantom_drain_detection` ([414-458](automations/06_enhancements.yaml:414)) computes staleness from `last_changed`: `ioniq_stale` ([436-439](automations/06_enhancements.yaml:436)) and `vf9_stale` ([440-443](automations/06_enhancements.yaml:440)) both require `(as_timestamp(now()) - as_timestamp(<soc>.last_changed)) > 86400`. But `last_changed` on a numeric sensor advances whenever the value changes — a battery actually suffering phantom drain reports a new, lower SoC every few hours, resetting `last_changed` and making `*_stale` permanently false. **The condition is satisfied exactly when the battery is healthy and holding charge.**

Secondary defect: the IONIQ branch is gated on `ioniq_home` ([427](automations/06_enhancements.yaml:427)), but the VF9 branch has **no location term at all** — the vinfast integration exposes no `device_tracker`, only lat/lon/address sensors. This contradicts the automation's own description at [line 421](automations/06_enhancements.yaml:421) ("if either car is home"). Trigger is `time_pattern hours: "/6"` with no dedupe latch.

**Failure scenario (upper bound).** The VF9 is parked at an airport for five days at 74%, holding charge. `vf9_soc > 0 and vf9_soc < 90 and not charging and last_changed > 86400` is all true, with nothing to suppress it, so every 6 hours the phone gets "Possible Phantom Drain". Meanwhile a real vampire drain taking the IONIQ 80% → 45% over two days updates `last_changed` on every step and is never reported.

**Fix.** Detect drain by comparing SoC against a stored baseline, not by `last_changed`: record SoC to an `input_number` each run and alert when `baseline - current > 3` while home and not charging. Keep `last_changed` only as a separately-worded "telemetry stale / vehicle offline" notice. Add a location gate to the VF9 branch (see [E8](#e8-give-the-vf9-a-home-presence-sensor-so-its-automations-match-the-ioniqs)). Add an `input_boolean` latch so the /6h pattern cannot re-nag.

**Live check:** Developer Tools → Template → `{{ (as_timestamp(now()) - as_timestamp(states.sensor.vf9_rllv2cja5rh000847_phan_tram_pin.last_changed)) / 3600 }}` and the same for `sensor.ioniq_6_ev_battery_level`. If neither ever approaches 24, this reduces to a dead heuristic with a misleading title rather than an alert-spam source. The inversion and the missing VF9 gate are certain either way. Note also that if the integration goes `unavailable` while the car sleeps, `vf9_soc` parses to 0 and `vf9_soc > 0` suppresses the alert entirely.

---

### A14. Door-ajar monitor watches a VF9 entity that does not exist — the rear-left door is never covered
**[repo-confirmed]** — [automations/06_enhancements.yaml:902](automations/06_enhancements.yaml:902)

Trigger id `rear_left_door` points at `sensor.vf9_rllv2cja5rh000847_cua_sau_trai`, which is absent from `.storage/core.entity_registry` and from the 186-entity dump. The real entity is `sensor.vf9_rllv2cja5rh000847_cua_sau_tai_xe` ("Rear Left Door"), which is currently referenced nowhere. The VF9's slugs are inconsistent by design — the integration used `tai_xe`/`phu` (driver/passenger) for doors but `trai`/`phai` (left/right) for tires, and this trigger applied the tire convention to a door. Tellingly, [line 921](automations/06_enhancements.yaml:921) in the same trigger block uses `kinh_sau_tai_xe` for the rear-left *window*, i.e. the correct convention appears 19 lines below the door that got it wrong. All nine other trigger ids in the block resolve, as does the speed gate `toc_do_hien_tai` at [line 928](automations/06_enhancements.yaml:928). This is the only unresolved entity_id in the entire loaded EV config.

**Failure scenario.** Someone leaves the VF9's rear-left door ajar in the driveway overnight. Nine of ten triggers are live so the automation looks healthy, but no state change ever arrives for the nonexistent entity and the 60-minute alert never sends for that door. HA logs nothing for a trigger on a nonexistent entity, so it fails invisibly — silent partial coverage, worse than none, because the user believes all four doors are watched.

**Fix.** Single-token change at [line 902](automations/06_enhancements.yaml:902):

```yaml
  - entity_id: sensor.vf9_rllv2cja5rh000847_cua_sau_tai_xe
```

---

### A15. `preflight.sh` prints "preflight OK" and exits 0 when PyYAML is missing
**[repo-confirmed]** — [verification/preflight.sh:59](verification/preflight.sh:59)

Lines [24-27](verification/preflight.sh:24) probe three interpreters for PyYAML; if none has it, [59-61](verification/preflight.sh:59) print `SKIP: PyYAML not installed` but leave `fail=0`, so [line 65](verification/preflight.sh:65) prints **"preflight OK — full validation still requires check_config on the Pi"** and [line 69](verification/preflight.sh:69) exits 0. A completely broken `configuration.yaml` ships with a green light. Secondarily, [line 17](verification/preflight.sh:17) enumerates the `.py` files that *exist* with no manifest of what *should* exist, which is why the deletion of four curated daemons in `1e2cf44` passed preflight perfectly clean.

Worth noting on the positive side: [line 38](verification/preflight.sh:38) does glob `dashboards/*.yaml`, so `dashboards/ev-charging.yaml` **is** syntax-checked tag-agnostically. [Line 37](verification/preflight.sh:37) wastes a check on the legacy, never-loaded root `automations.yaml`.

**Failure scenario.** A contributor runs preflight on a Mac where `hq_venv` was rebuilt without PyYAML. They introduce a tab-indentation error into the `utility_meter:` block. Preflight prints SKIP, then "preflight OK", exit 0. Because `AGENTS.md:23-27` mandates `check_config` as a separate gate, this only reaches production if that step is also skipped — but a gate that cannot check must not report OK.

**Fix.** Set `fail=1` in the `else` branch at [59-61](verification/preflight.sh:59). Add an expected-daemons manifest:

```bash
for f in grizzl_e_daemon.py tuya_kitchen_bridge.py tuya_listener.py \
         update_kitchen_presence.py check_garage_vision.py; do
  [ -f "$f" ] || { echo "FAIL: missing curated daemon $f"; fail=1; }
done
```

Drop `automations.yaml` from [line 37](verification/preflight.sh:37).

**Reproduce:** `PREFLIGHT_PYTHON=/usr/bin/false bash verification/preflight.sh; echo "exit=$?"`

---

### A16. VF9 weekly summary reports lifetime totals labelled "This week", denominated in Vietnamese Dong
**[repo-confirmed]** — [automations/06_enhancements.yaml:1168](automations/06_enhancements.yaml:1168)

`vf9_charging_cost_weekly_summary` ([1154-1179](automations/06_enhancements.yaml:1154)) reads five sensors at [1168-1172](automations/06_enhancements.yaml:1168) and renders "This week: {{ total_kwh }} kWh charged ({{ home_kwh }} at home). Total charging cost: … Savings: …" at [1177-1179](automations/06_enhancements.yaml:1177). Two independent problems:

1. **Period.** None of these are weekly. `api.py:203` computes `api_total_charge_cost_est` from the **lifetime** `api_total_energy_charged`, and `api.py:206-207` computes `api_total_gas_cost` from the **lifetime odometer**. `home_kwh` is the same never-reset accumulator as A4. Every value is monotonically increasing, so the message grows every week and conveys no weekly information whatever.
2. **Currency.** `tong_chi_phi_sac_quy_doi`, `chi_phi_sac_chuyen_di` and `tong_chi_phi_xang_tuong_duong` all carry unit **VNĐ** in the entity registry. The integration's defaults are `cost_per_kwh = 4000` and `gas_price = 20000` (`api.py:197-198`) — dong per kWh and per litre, unrelated to the Ontario CAD tariffs used throughout this file ([3.9¢ at line 82](automations/06_enhancements.yaml:82), [39.1¢ at line 484](automations/06_enhancements.yaml:484)). *Caveat:* those are config-entry option **defaults** and `.storage/core.config_entries` is gitignored, so the actual configured values are unproven from this worktree. The period defect stands regardless.

Note the arithmetic at [line 1179](automations/06_enhancements.yaml:1179) is *not* cross-currency — `gas_equiv` and `total_cost` are both VNĐ, so the subtraction is sound. The defect is an unlabelled foreign-currency figure in a CAD household plus a lifetime figure labelled weekly.

**Fix.** Either (a) drop the currency figures and report only kWh, replacing the lifetime sensors with `utility_meter` helpers on `cycle: weekly` sourced from `sensor.vf9_..._tong_dien_nang_da_sac`; or (b) reconfigure the vinfast integration options to CAD and relabel [line 1177](automations/06_enhancements.yaml:1177) from "This week" to "Lifetime". `08_ev_per_vehicle_cost_tracking.yaml` already tracks true CAD cost for the VF9 in `input_number.vf9_total_cost_cents` — prefer that as the money source.

**Check the configured tariff:** Settings → Devices & Services → VinFast → Configure.

---

### A17. Fixed-cost accumulator ceiling is hit in month 30, and the failing `set_value` silences the monthly report
**[needs live check]** — [configuration.yaml:326](configuration.yaml:326)

`input_number.ev_fixed_cost_accumulated_cents` has `max: 100000` ($1000.00) while [automations/08_ev_per_vehicle_cost_tracking.yaml:149](automations/08_ev_per_vehicle_cost_tracking.yaml:149) adds 3357 cents monthly. 100000 / 3357 = 29.79, so after 29 months the value is 97353 and month 30 attempts 100710. `input_number.set_value` outside min/max raises, and the failing call at [08:155-159](automations/08_ev_per_vehicle_cost_tracking.yaml:155) is the **first** step of the sequence, so the `notify` at [08:160-166](automations/08_ev_per_vehicle_cost_tracking.yaml:160) never runs. `input_number.ev_unknown_cost_cents` ([configuration.yaml:334](configuration.yaml:334)) shares the same ceiling and, given A8, is the bucket most likely to actually fill.

**Failure scenario.** On the 1st of month 30 HA throws `Invalid value for input_number.ev_fixed_cost_accumulated_cents (range 0.0 - 100000.0): 100710.0`. The accumulator freezes at 97353 forever, `sensor.ev_fixed_cost_total` freezes with it, and the monthly reconciliation goes silent from then on with only a logbook error. Currently latent: A1 zeroes the accumulator before it can climb that high, so this becomes live the moment `initial:` is removed.

**Fix.** Raise `max` on both helpers to `1000000`, matching the per-vehicle cost helpers at [278](configuration.yaml:278)/[286](configuration.yaml:286), and reorder the sequence so the notification is sent before the `set_value` (or wrap the `set_value` in `continue_on_error: true`).

**Live check:** Developer Tools → Actions → `input_number.set_value` on `ev_fixed_cost_accumulated_cents` with value 200000; observe whether it errors or silently clamps.

---

### A18. The fixed monthly charge is hardcoded in three places, and per-vehicle cost sensors use a different unit string from the charger sensor
**[repo-confirmed]** — [automations/08_ev_per_vehicle_cost_tracking.yaml:149](automations/08_ev_per_vehicle_cost_tracking.yaml:149)

[grizzl_e_rates.json:16-17](grizzl_e_rates.json:16) is the declared source of truth (`service_charge: 33.32` + `regulatory_supply: 0.25` = 33.57), which the daemon publishes as the `fixed_monthly_cad` attribute on `sensor.grizzl_e_total_cost` and which [configuration.yaml:730](configuration.yaml:730) consumes for `sensor.grizzl_e_est_monthly_bill`. Two consumers bypass it: [08:149](automations/08_ev_per_vehicle_cost_tracking.yaml:149) hardcodes `fixed_monthly_cents: 3357` (with 33.57 repeated in the description at [08:135](automations/08_ev_per_vehicle_cost_tracking.yaml:135) and the fallback message at [08:171](automations/08_ev_per_vehicle_cost_tracking.yaml:171)), and [configuration.yaml:730](configuration.yaml:730) hardcodes 33.57 as its `default()` fallback. [grizzl_e_rates.json:3](grizzl_e_rates.json:3) declares `valid_through: 2026-10-31` — a change is scheduled, not hypothetical.

**Failure scenario.** Alectra raises the service charge on 2026-11-01. The user updates `grizzl_e_rates.json`; the daemon picks it up and `sensor.grizzl_e_est_monthly_bill` reflects the new figure immediately. `ev_monthly_reconciliation` keeps adding 3357 cents and keeps quoting $33.57. From then on `sensor.ev_fixed_cost_total` and `sensor.grizzl_e_est_monthly_bill` — two dashboard tiles both labelled as the same fixed delivery cost — disagree by a widening amount every month with nothing to flag it.

**Fix.**

```yaml
        fixed_monthly_cents: >
          {{ (state_attr('sensor.grizzl_e_total_cost','fixed_monthly_cad')
              | default(33.57, true) | float(33.57) * 100) | round(0) | int }}
```

Template the `$` figures in the messages at [08:164](automations/08_ev_per_vehicle_cost_tracking.yaml:164) and [08:171](automations/08_ev_per_vehicle_cost_tracking.yaml:171) from the same variable, and drop the hardcoded amount from the header comment at [08:13](automations/08_ev_per_vehicle_cost_tracking.yaml:13).

**Related, cosmetic:** `sensor.grizzl_e_total_cost` uses `unit_of_measurement: "$"` ([configuration.yaml:673](configuration.yaml:673)) while `sensor.ev_ioniq_6_total_cost` / `ev_vf9_total_cost` / `ev_fixed_cost_total` use `"CAD"` ([818](configuration.yaml:818), [824](configuration.yaml:824), [842](configuration.yaml:842)). None of the three carries `device_class: monetary`, so this is a display-string inconsistency rather than a statistics hazard — but the Overview and Per-Vehicle views present the same quantity in two different units. Standardise on one.

---

### A19. The session-end default branch fires on successful detections whenever session cost is zero
**[needs live check]** — [automations/08_ev_per_vehicle_cost_tracking.yaml:114](automations/08_ev_per_vehicle_cost_tracking.yaml:114)

Both `choose` conditions require `session_cost_cents > 0` in addition to the vehicle match ([08:68](automations/08_ev_per_vehicle_cost_tracking.yaml:68), [08:92](automations/08_ev_per_vehicle_cost_tracking.yaml:92)). `session_cost_cents` is pulled from a daemon attribute at [08:61](automations/08_ev_per_vehicle_cost_tracking.yaml:61) and defaults to 0 when missing, stale-zeroed, or unavailable. There is no branch for "vehicle known but cost zero", so that case lands in `default:` ([114-128](automations/08_ev_per_vehicle_cost_tracking.yaml:114)), which is worded as a detection failure.

**Failure scenario.** The daemon clears `session_cost_cents` shortly after the charger goes off. The automation waits a full 2 minutes and the command_line sensor re-reads the JSON every 15s ([configuration.yaml:676](configuration.yaml:676)), so a cleared attribute is very likely what it sees. `sensor.ev_charging_vehicle_detected` correctly says `ioniq_6`, but the automation adds 0 to `ev_unknown_cost_cents`, overwrites `input_text.ev_session_vehicle` with `unknown` at [08:124](automations/08_ev_per_vehicle_cost_tracking.yaml:124) — destroying the correct detection the dashboard shows at [dashboards/ev-charging.yaml:216](dashboards/ev-charging.yaml:216) — and pushes "vehicle could not be identified… Manual attribution needed" to both phones for a session that *was* identified.

**Fix.** Add a fourth `choose` branch for `vehicle in ['ioniq_6','vf9'] and session_cost_cents == 0` that writes the detected vehicle to `input_text.ev_session_vehicle` and either skips the notify or sends a distinct "zero-cost session" message, reserving the alarming default branch for genuine detection failures.

**Live check:** `ssh pi 'cat /opt/homeassistant/grizzl_e_state.json'` immediately after a session ends — is `session_cost_cents` retained or zeroed?

---

### A20. Charging-complete notification templates lack the `default(0, true)` guards used everywhere else
**[repo-confirmed]** — [automations/05_grizzl_e_charging.yaml:37](automations/05_grizzl_e_charging.yaml:37)

The "stopped" branch builds its message from three unguarded expressions: [37](automations/05_grizzl_e_charging.yaml:37) `state_attr(...,'session_energy_kwh') | round(2)`, [38](automations/05_grizzl_e_charging.yaml:38) `(state_attr(...,'session_cost_cents') / 100) | round(2)`, and [39-40](automations/05_grizzl_e_charging.yaml:39) `states('sensor.grizzl_e_energy_daily') | round(2)`. When the source is unavailable, `state_attr` returns `None`: line 38's raw `None / 100` raises TypeError, and `forgiving_round` raises "no default was specified" for `None` and for `unavailable`/`unknown`. **Every** other consumer of these attributes is guarded — [configuration.yaml:759](configuration.yaml:759), [767](configuration.yaml:767), [770](configuration.yaml:770), [787](configuration.yaml:787), [806](configuration.yaml:806), [809](configuration.yaml:809), and [08:61-64](automations/08_ev_per_vehicle_cost_tracking.yaml:61). File 05 is the sole exception.

**Failure scenario (narrow).** The normal charge-stop path is safe — both the binary sensor and the cost sensor read the same JSON at 15s intervals. If the state file disappears entirely, the binary sensor goes `unavailable` rather than `off`, so the `to: "off"` trigger never fires. The genuinely reachable path is HA startup, where the binary sensor's first scan (`unknown → off`) fires the trigger while `sensor.grizzl_e_total_cost` may still be unknown — which would have produced a spurious "EV Charging Complete" push anyway, so the loss is minor. Fix it for consistency, not urgency.

**Fix.** Apply the repo's own convention to [05:37-40](automations/05_grizzl_e_charging.yaml:37): `... | default(0, true) | float(0) | round(2)`. Lines [26-27](automations/05_grizzl_e_charging.yaml:26) render the literal string "None" rather than raising — add `| default('unknown', true)` for cosmetics.

---

### A21. VF9 battery-degradation trigger can never fire — the backing sensor is never populated
**[needs live check]** — [automations/06_enhancements.yaml:983](automations/06_enhancements.yaml:983)

`vf9_battery_health_monitor` ([972-995](automations/06_enhancements.yaml:972)) has a second trigger on `sensor.vf9_..._do_chai_pin_theo_soh`, `above: 20`, id `degradation_high` ([983-986](automations/06_enhancements.yaml:983)). That entity maps to `api_battery_degradation`, declared once in `custom_components/vinfast/const_common.py:12` and **never written into `_last_data` anywhere** — a repo-wide grep for `battery_degradation` across the integration returns only that declaration. `sensor.py:~61` (`if self._device_key in data:`) means the value is never assigned, so the state stays `unknown` and a `numeric_state` trigger never fires. Compounding: the registry unit is **kWh**, not %, yet [line 995](automations/06_enhancements.yaml:995) prints "degradation: {{ deg }}%", and [line 991](automations/06_enhancements.yaml:991)'s `| float(0)` turns `unknown` into 0.

**Failure scenario.** The `degradation_high` branch is dead code. When the *other* trigger fires (SOH below 80, [979-982](automations/06_enhancements.yaml:979)), the message reads "SOH low. SOH: 79.0%, degradation: 0.0%." — a fabricated 0.0% that misleads the reader into thinking degradation is nil while SOH is failing.

**Fix.** Remove the trigger at [983-986](automations/06_enhancements.yaml:983), the `deg` variable at [991](automations/06_enhancements.yaml:991), and the degradation clause from the message at [995](automations/06_enhancements.yaml:995). If a second degradation signal is wanted, use `sensor.vf9_..._suc_khoe_pin_soh_tinh_toan` ("Battery Health (SOH Calculated)", %), which the integration does populate at `api.py:176-182`. The trigger-id ternary at [995](automations/06_enhancements.yaml:995) then always resolves to "SOH low" and can be simplified.

**Live check:** Developer Tools → Template → `{{ states('sensor.vf9_rllv2cja5rh000847_do_chai_pin_theo_soh') }}` — expect `unknown`/`unavailable`. (The integration persists `_last_data` to a state file, so a stale value from an older build could in principle linger.)

---

### A22. `reference/entities.md` documents a state the template can never emit and calls reset-on-restart helpers "lifetime"
**[repo-confirmed]** — [reference/entities.md:55](reference/entities.md:55)

Two contradictions with the config:

- [entities.md:55](reference/entities.md:55) documents `sensor.ev_charging_vehicle_detected` as "(states: ioniq_6, vf9, unknown, **inactive**)". The template at [configuration.yaml:780-802](configuration.yaml:780) has exactly four return paths — `ioniq_6` ([789](configuration.yaml:789)), `vf9` ([791](configuration.yaml:791)), one of those two from the tie-break ([796](configuration.yaml:796)/[798](configuration.yaml:798)), or `unknown` ([801](configuration.yaml:801)). There is no `inactive` path and no availability template, so it never goes unavailable either.
- [entities.md:42-49](reference/entities.md:42) describes `input_number.ioniq_6_total_cost_cents` and siblings as "lifetime" accumulators, which is false given A1.

**Failure scenario.** A future contributor (or an AI agent following `AGENTS.md`'s pointer to entities.md as *the* entity reference) writes `condition: state / state: 'inactive'` to gate on "charger idle". That condition is never true, the automation never runs, and HA does not flag an impossible-but-syntactically-valid state string.

**Fix.** Correct [entities.md:55](reference/entities.md:55) to `(states: ioniq_6, vf9, unknown)`. Either reword [entities.md:42-49](reference/entities.md:42) to "resets on HA restart" or — better — remove the `initial:` keys per A1 and let the docs become true. Also worth noting: `README.md`, `plan.md` and `walkthrough.md` contain **zero** occurrences of grizzl/EV/IONIQ/VF9. The entire EV subsystem is absent from every architecture doc; add a short section covering the daemon → state file → command_line sensor → utility_meter chain, since that is the only place a reader would learn the pipeline has an external, non-HA producer.

---

### A23. Every charging session sends 3 push notifications, 5 for the VF9 — from four automations that never coordinate
**[repo-confirmed]** — [automations/05_grizzl_e_charging.yaml:12](automations/05_grizzl_e_charging.yaml:12)

Four independent automations trigger off the end of the same charging session, and each one notifies:

| Automation | Trigger | Target |
|---|---|---|
| `grizzl_e_charging_notify` | [05:12](automations/05_grizzl_e_charging.yaml:12) — `grizzl_e_charging` → `off`, immediate | `grizzl_ev_phones` (both) |
| `ev_soc_energy_reconciliation` | [06:359](automations/06_enhancements.yaml:359) — same edge, `for: 2min` | `mobile_app_cph2655` (one) |
| `ev_session_end_attribute_cost` | [08:55](automations/08_ev_per_vehicle_cost_tracking.yaml:55) — same edge, `for: 2min` | `grizzl_ev_phones` (both) |
| `ev_vf9_soc_energy_reconciliation` + `vf9_charging_session_summary` | [06:391](automations/06_enhancements.yaml:391), [06:1007](automations/06_enhancements.yaml:1007) — VF9 charge-state edge, `for: 2min` | one each |

All three branches of the `08` `choose` notify, including the `unknown` fallback at [08:125](automations/08_ev_per_vehicle_cost_tracking.yaml:125) — there is no silent path.

**Failure scenario.** Plugging in the VF9 overnight produces five pushes within ~2 minutes of unplugging, three of which restate the same session energy in different words, and two of which (per A4) carry a lifetime figure labelled as the session. The OnePlus gets all five, the Samsung three. Alert fatigue here is not cosmetic — it is what makes the genuinely important ones (A5's security alerts, the "vehicle not detected" fallback that needs manual attribution) get swiped away unread.

Targeting is also split with no rule behind it: across the three EV automation files there are **21** uses of `notify.mobile_app_cph2655` against **14** of the `notify.grizzl_ev_phones` group, so Larissa's handset silently misses a majority of EV alerts.

**Fix.** Collapse to one session-end notification. Keep `08`'s (it is the only one that knows which car charged and what it cost), delete the notify blocks from [05:32-40](automations/05_grizzl_e_charging.yaml:32) and [06:374-380](automations/06_enhancements.yaml:374), and fold the reconciliation numbers into `08`'s message. Then standardise every remaining EV notify on `notify.grizzl_ev_phones`.

---

### A24. Both VF9 charge-stop triggers use `from:` with no `to:`, so an integration dropout counts as "charging finished"
**[repo-confirmed]** — [automations/06_enhancements.yaml:391](automations/06_enhancements.yaml:391)

`ev_vf9_soc_energy_reconciliation` ([06:390-393](automations/06_enhancements.yaml:390)) and `vf9_charging_session_summary` ([06:1006-1009](automations/06_enhancements.yaml:1006)) both trigger on `sensor.vf9_..._trang_thai_sac` with `from: 'Charging'` and **no `to:`**. An HA state trigger that specifies only `from:` fires on *any* departure from that value — including to `unavailable` and `unknown`. Neither automation has a condition filtering those out (`conditions: []` at [394](automations/06_enhancements.yaml:394) and [1010](automations/06_enhancements.yaml:1010)).

The `for: "00:02:00"` qualifier does not help: an MQTT dropout holds `unavailable` well past two minutes, which is exactly the case that satisfies it.

**Failure scenario.** The VF9's MQTT link drops mid-charge at 02:00. Two minutes later both automations fire a "charging session ended" summary while the car is still drawing power, reporting a plug-in/unplug SoC pair from the *previous* session. When the link recovers the state returns to `Charging`, and the real end-of-session fires the same two notifications again — so one interrupted session yields two contradictory summaries.

**Fix.** Constrain the destination on both triggers:

```yaml
  - entity_id: sensor.vf9_rllv2cja5rh000847_trang_thai_sac
    trigger: state
    from: 'Charging'
    not_to:
      - unavailable
      - unknown
    for: "00:02:00"
```

**Live check** — confirm the idle state string before pinning `to:` instead of `not_to:`: Developer Tools → States → filter `trang_thai_sac`, and watch it while the car is unplugged.

---

## 1. Is the EV Charging dashboard set up properly?

Structurally yes — three views (Overview, History, Per-Vehicle), sensible card choices, and it does get syntax-checked by preflight. But the Current Session card is silently broken, the trend charts plot the wrong statistic, and the History view presents modeled data adjacent to metered data with no reconciliation.

### D1. Seven rows use `attribute:`/`suffix:` without `type: attribute` — three rows render the identical lifetime figure
**[needs live check]** — [dashboards/ev-charging.yaml:78](dashboards/ev-charging.yaml:78)

*The seven rows and their missing `type: attribute` are repo-confirmed. What Lovelace **does** with them could not be verified from this machine — no HA frontend source is installed here — so the rendering claim below is reasoned from the card schema, not observed. Two failure modes are possible: the attribute is silently ignored (parent state renders), or the row config is rejected (error card). **The check is free: open the EV Charging dashboard and look at the Current Session card. If "Session Energy", "Rate Period" and "Rate" all show the same dollar figure, this is confirmed on sight.***

`attribute:`, `prefix:` and `suffix:` belong to the Lovelace **attribute row** (`hui-attribute-row`), which is only instantiated when the row config carries `type: attribute`. A row with only `entity:` is routed by domain; `sensor.*` maps to the sensor entity row, which renders the entity state and never reads `attribute`. Lovelace does not strictly validate unknown row keys, so both are dropped with no error and no repair notice.

Affected rows: [78-82](dashboards/ev-charging.yaml:78) (`grizzl_e_total_cost` + `session_energy_kwh` + `" kWh"`), [86-89](dashboards/ev-charging.yaml:86) (same entity + `period_label`), [90-94](dashboards/ev-charging.yaml:90) (same entity + `rate_cents_kwh` + `" ¢/kWh"`), [114-118](dashboards/ev-charging.yaml:114) (`grizzl_e_power` + `rssi_dbm` + `" dBm"`), and [218-220](dashboards/ev-charging.yaml:218) / [221-223](dashboards/ev-charging.yaml:221) / [224-226](dashboards/ev-charging.yaml:224) (`ev_charging_vehicle_detected` + `ioniq_soc_gain` / `vf9_soc_gain` / `session_kwh`). All the referenced attributes genuinely exist — `json_attributes` at [configuration.yaml:678-684](configuration.yaml:678) and [634-637](configuration.yaml:634), template attributes at [803-814](configuration.yaml:803). The dashboard simply cannot reach them.

**Failure scenario.** Mid-session, `sensor.grizzl_e_total_cost` = 41.87 (lifetime $) with `session_energy_kwh=12.4`, `period_label=overnight`, `rate_cents_kwh=3.9`. The 🔌 Current Session card renders "Session Energy $41.87 / Session Cost $1.02 / Rate Period $41.87 / Rate $41.87" — three rows showing the same lifetime dollar figure under three different labels, with the kWh and ¢/kWh suffixes never appearing. The 📡 Diagnostics card shows "Wi-Fi RSSI 3421 W" (the charger's live wattage) instead of dBm. The Per-Vehicle Current Session card shows "IONIQ SoC Gain / VF9 SoC Gain / Session kWh" all reading the string `ioniq_6` — making the attribution debug view useless precisely when attribution fails.

**Fix.** Add `type: attribute` to all seven rows:

```yaml
          - type: attribute
            entity: sensor.grizzl_e_total_cost
            attribute: session_energy_kwh
            name: Session Energy
            icon: mdi:battery-charging
            suffix: " kWh"
```

Alternatively expose each attribute as its own template sensor and use plain rows.

**Visual confirmation:** open the Overview → 🔌 Current Session card and check whether "Session Energy", "Rate Period" and "Rate" all show the same dollar value.

---

### D2. History view labels 5 days of metered data "Lifetime" above a 20-month modeled table whose own totals are wrong
**[repo-confirmed]** — [dashboards/ev-charging.yaml:138](dashboards/ev-charging.yaml:138)

The "Lifetime Totals" card ([134-146](dashboards/ev-charging.yaml:134)) shows `sensor.grizzl_e_total_energy` as "Lifetime Energy" ([139](dashboards/ev-charging.yaml:139)) and `sensor.grizzl_e_total_cost` as "Lifetime Cost" ([142](dashboards/ev-charging.yaml:142)). Both entities were created **2026-07-26T04:17:51Z** per `.storage/core.entity_registry` — five days of data. Their values come from `grizzl_e_history.json`, which the daemon seeds to `0.0` when absent, so they provably contain nothing before the daemon's first start.

Immediately below, [166-193](dashboards/ev-charging.yaml:166) renders a hardcoded table totalling **14,294 kWh / $1,102 over 20 months** (Nov 2024 – Jun 2026). Two hard defects:

- **The table's own arithmetic is wrong.** The 20 data rows at [171-190](dashboards/ev-charging.yaml:171) sum to **14,296 kWh and $1,100**, not the 14,294 / $1,102 stated at [line 191](dashboards/ev-charging.yaml:191) — kWh 2 low, cost $2 high.
- **Twelve of the twenty months predate [grizzl_e_rates.json:2](grizzl_e_rates.json:2)'s `"effective": "2025-11-01"`**, so they were modeled with rates not then in force.

(The implied 7.69 ¢/kWh blended rate is *not* evidence of a problem — it sits between the 6.79 ¢ overnight and 12.91 ¢ weekend off-peak marginal rates and is consistent with roughly an 85/15 mix.)

**Failure scenario.** A user opens History to reconcile against an Alectra bill. "Lifetime Cost" reads a five-day figure (order of $10) while the table two cards down asserts $1,102. Nothing on the page reconciles them, and no sensor anywhere in the config contains the 14,294 kWh. The disclaimer at [line 132](dashboards/ev-charging.yaml:132) does exist and is explicit ("Nov 2024 – Jun 2026: modeled … Jul 2026+: live metered data") but sits in a separate card two above the mislabeled one. A user who adds the monthly rows by hand gets $1,100 and cannot match the stated $1,102, which corrodes trust in the whole dataset.

**Fix.**
1. Rename [139](dashboards/ev-charging.yaml:139)/[142](dashboards/ev-charging.yaml:142) to "Metered Energy (since 2026-07-26)" / "Metered Cost (since 2026-07-26)".
2. Correct [line 191](dashboards/ev-charging.yaml:191) to `| **Total** | **14,296** | **$1,100** | **20 months** |` (or fix the mistyped rows). The averages at [193](dashboards/ev-charging.yaml:193) hold either way — both totals round to 715 kWh/mo and $55/mo.
3. Move the modeled table into its own card titled e.g. `### MODELED ESTIMATE — not measured`, repeating the disclaimer inside that card and stating that the modeled and metered figures are not additive.

**One-line sanity check on the premise:** Developer Tools → States → `sensor.grizzl_e_total_energy` (or on the Pi, `cat /opt/homeassistant/grizzl_e_state.json`). If it reads in the thousands of kWh, the counter genuinely is lifetime and only the arithmetic error at [line 191](dashboards/ev-charging.yaml:191) survives; if it reads in the low hundreds, the mislabeling holds as described.

---

### D3. `stat_types: sum` on utility_meter sensors plots the cumulative-across-resets total, not the per-period value
**[needs live check]** — [dashboards/ev-charging.yaml:101](dashboards/ev-charging.yaml:101)

`sensor.grizzl_e_cost_daily` and `sensor.grizzl_e_energy_daily` are utility_meters ([configuration.yaml:873-897](configuration.yaml:873)) reporting `state_class: total` with `last_reset`. The recorder's long-term `sum` statistic for a TOTAL sensor accumulates deltas *across* meter resets, so `sum` is a monotonically rising lifetime figure, not the per-bucket value. The card asks for `sum` in three places: [101](dashboards/ev-charging.yaml:101) ("Cost Trend (30d)"), [152](dashboards/ev-charging.yaml:152) ("Monthly Energy (365 days)") and [161](dashboards/ev-charging.yaml:161) ("Monthly Cost (365 days)"). The statistic that yields the per-bucket delta is `change`. Additionally, the two cards at [148-164](dashboards/ev-charging.yaml:148) are titled "Monthly" but set no `period: month`.

**Failure scenario.** After six months the lifetime cost sum is ~$330. "Cost Trend (30d)" renders 30 bars all in the 320-330 range — a near-flat wall of full-height bars with no day-to-day variation. A zero-charging day is indistinguishable from a $4 day. The two 365-day charts show a year of near-identical cumulative bars, bucketed at something other than monthly despite their titles.

**Fix.** `stat_types: [sum]` → `stat_types: [change]` at [101-102](dashboards/ev-charging.yaml:101), [152-153](dashboards/ev-charging.yaml:152) and [161-162](dashboards/ev-charging.yaml:161). Add `period: month` to the two History cards so buckets match their titles (with `days_to_show: 365` that yields 12 bars).

**Live check:** Developer Tools → Statistics → `grizzl_e_cost_daily`, or websocket `recorder/statistics_during_period` with `period: day` — confirm `sum` rises monotonically and never resets while `change` gives the per-day value. (I proved the buckets are not monthly; I did not verify what the fallback period actually is.)

---

### D4. Per-vehicle cost-trend charts set `period: month` but omit `days_to_show`, giving a 2-point line
**[repo-confirmed]** — [dashboards/ev-charging.yaml:303](dashboards/ev-charging.yaml:303)

"IONIQ 6 Cost Trend" ([299-306](dashboards/ev-charging.yaml:299)) and "VF9 Cost Trend" ([307-314](dashboards/ev-charging.yaml:307)) declare `period: month` with `chart_type: line` and `stat_types: [sum]`, but never set `days_to_show`, which defaults to 30 — a window spanning at most two monthly buckets.

**Failure scenario.** The card draws a single straight segment between two nearly identical cumulative-total values: a flat line labelled "Cost Trend" that conveys nothing. It cannot show a trend at any point in the month.

**Fix.** Add `days_to_show: 365` to both, switch `stat_types: [sum]` → `[change]` (same root cause as D3), and use `chart_type: bar`, which reads better for monthly buckets.

---

### D5. All four `grid` cards omit `square: false`
**[repo-confirmed]** — [dashboards/ev-charging.yaml:229](dashboards/ev-charging.yaml:229)

The grid card's `square` option defaults to **true**, which forces every cell to the column width via `grid-auto-rows: 1fr`. Four `columns: 2` grids have no `square: false`: [229-253](dashboards/ev-charging.yaml:229), [256-280](dashboards/ev-charging.yaml:256), [283-293](dashboards/ev-charging.yaml:283) and [296-314](dashboards/ev-charging.yaml:296).

**Failure scenario.** No view in this file declares `type:`, so all three are default masonry with a capped column width (~500px) — the impact is smaller than a full-width layout would suffer. Two cases are still concretely wrong: the statistics-graph pair at [296-314](dashboards/ev-charging.yaml:296), where the chart's own fixed height fights the forced square row; and narrow-phone single-column rendering, where a 3-row entities card is squeezed into a ~170px cell and overflows.

**Fix.** Add `square: false` under each `columns: 2` ([230](dashboards/ev-charging.yaml:230), [257](dashboards/ev-charging.yaml:257), [284](dashboards/ev-charging.yaml:284), [297](dashboards/ev-charging.yaml:297)). For the two-chart row at [296](dashboards/ev-charging.yaml:296), `type: horizontal-stack` is a better fit — it never imposes an aspect ratio.

---

### D6. The eight per-vehicle utility_meters have no `unique_id`, so they are absent from the entity registry
**[repo-confirmed]** — [configuration.yaml:916](configuration.yaml:916)

Cross-checking every entity_id in the dashboard against `.storage/core.entity_registry` (1861 entities): 23 of 31 resolve and exactly 8 do not — `sensor.ioniq_6_cost_daily`, `_cost_monthly`, `_energy_daily`, `_energy_monthly` and the four `vf9_*` equivalents, referenced at dashboard lines [239](dashboards/ev-charging.yaml:239), [241](dashboards/ev-charging.yaml:241), [250](dashboards/ev-charging.yaml:250), [252](dashboards/ev-charging.yaml:252), [266](dashboards/ev-charging.yaml:266), [268](dashboards/ev-charging.yaml:268), [277](dashboards/ev-charging.yaml:277), [279](dashboards/ev-charging.yaml:279). The cause is that the definitions at [configuration.yaml:915-939](configuration.yaml:915) supply only `source:` and `cycle:` — no `unique_id:` and no `name:` — unlike the eight Grizzl-E meters directly above at [874-912](configuration.yaml:874), which all carry both and are all registry-present. HA only registers entities that provide a unique_id.

They still produce states (entity_id is slugified from the config key), so the dashboard rows resolve and long-term statistics still compile.

**Failure scenario.** The user cannot rename, hide, set an `entity_category` on, or assign an area to any of the eight — Settings → Devices & Services → Entities does not list them, with no error explaining why. Their friendly name is the raw slug `ioniq_6_cost_daily`; only the dashboard's explicit `name:` overrides hide that, so they look unlabeled in search, more-info dialogs and voice. (They *can* still be picked in entity selectors, which enumerate `hass.states`, and in statistic-backed Energy pickers — the limitation is registry customization specifically.)

**Fix.** Add `unique_id:` to each of the eight at [916-939](configuration.yaml:916), matching the pattern used at [877](configuration.yaml:877)/[882](configuration.yaml:882)/[887](configuration.yaml:887)/etc. Keep the `unique_id` equal to the current key so recorder history is preserved; adding a `name:` changes the generated entity_id, so if you add one, update the eight dashboard references and [reference/entities.md:63-70](reference/entities.md:63) in the same change.

```yaml
  ioniq_6_cost_daily:
    source: sensor.ev_ioniq_6_total_cost
    name: "Ioniq 6 Cost Daily"
    unique_id: ioniq_6_cost_daily
    cycle: daily
```

---

### D7. *(enhancement)* The Per-Vehicle view omits every entity that drives vehicle attribution
**[repo-confirmed]** — [dashboards/ev-charging.yaml:209](dashboards/ev-charging.yaml:209)

No vehicle-side entity appears anywhere in the 315-line dashboard — no SoC, range, plug state, charge limit, or car-reported charging power. The "Current Session" card ([209-226](dashboards/ev-charging.yaml:209)) shows only `sensor.ev_charging_vehicle_detected` and `input_text.ev_session_vehicle`. But that detection sensor is computed ([configuration.yaml:786-806](configuration.yaml:786)) from exactly four inputs — `sensor.ioniq_6_ev_battery_level`, `sensor.vf9_..._phan_tram_pin`, and the two `input_number.ev_session_soc_start_*` baselines — none of which is on the dashboard.

**Failure scenario.** A session ends and automation 08 fires the "could not be identified" branch ([08:128](automations/08_ev_per_vehicle_cost_tracking.yaml:128)), dumping the cost into `ev_unknown_cost_cents`. The user opens Per-Vehicle to find out why and sees only "Detected Vehicle: unknown" — no live SoC, no session-start snapshot, no plug state — so there is no way to distinguish a stale cloud poll from a car that was never plugged in from both cars gaining >1%. The unattributed bucket grows with no diagnostic path.

**Fix.** Add after [line 226](dashboards/ev-charging.yaml:226):

```yaml
          - entity: sensor.ioniq_6_ev_battery_level
            name: IONIQ 6 SoC (live)
          - entity: input_number.ev_session_soc_start_ioniq
            name: IONIQ 6 SoC at plug-in
          - entity: binary_sensor.ioniq_6_ev_battery_plug
            name: IONIQ 6 Plugged In
          - entity: switch.ioniq_6_ev_charging
            name: IONIQ 6 Charging
          - type: divider
          - entity: sensor.vf9_rllv2cja5rh000847_phan_tram_pin
            name: VF9 SoC (live)
          - entity: input_number.ev_session_soc_start_vf9
            name: VF9 SoC at plug-in
          - entity: sensor.vf9_rllv2cja5rh000847_trang_thai_sac
            name: VF9 Charging Status
          - entity: sensor.vf9_rllv2cja5rh000847_cong_suat_sac
            name: VF9 Charging Power (car, kW)
```

Also worth a range/limit pair: `sensor.ioniq_6_ev_range` + `number.ioniq_6_ac_charging_limit`, and `sensor.vf9_..._quang_duong_du_kien` + `sensor.vf9_..._muc_tieu_sac_target`. Note `cong_suat_sac` is registered in **kW** while `sensor.grizzl_e_power` is in **W** ([configuration.yaml:629](configuration.yaml:629)) — label them so the units are not confused.

---

### D8. *(enhancement)* Three EV template sensors already defined are surfaced nowhere
**[repo-confirmed]** — [dashboards/ev-charging.yaml:107](dashboards/ev-charging.yaml:107)

`sensor.ev_charging_efficiency` ([configuration.yaml:761-775](configuration.yaml:761)), `sensor.monthly_ev_charging_cost` ([configuration.yaml:746-750](configuration.yaml:746)) and `sensor.home_daily_energy_cost_estimate` ([configuration.yaml:731-742](configuration.yaml:731)) are all defined, all registry-present, and absent from every card.

**Do not add `sensor.ev_charging_efficiency` as-is** — per A3 its formula is dimensionally wrong, so putting it on the Diagnostics card would display a meaningless number next to a documented range it can never reach. Fix A3 first, then add it after [line 118](dashboards/ev-charging.yaml:118) alongside its `expected_range` attribute: it is the only entity in the whole config that compares charger-delivered kWh against car-reported SoC gain, and is exactly the tripwire for a drifting meter.

`sensor.home_daily_energy_cost_estimate` can be added to the 💲 Charging Cost drill-down after [line 53](dashboards/ev-charging.yaml:53) so EV spend is visible against whole-home spend. Skip `sensor.monthly_ev_charging_cost` — see [Q4/T2](#t2-sensormonthly_ev_charging_cost-is-a-zero-consumer-passthrough-of-sensorgrizzl_e_cost_monthly), it should be deleted, not surfaced. The card at [line 51](dashboards/ev-charging.yaml:51) already uses `sensor.grizzl_e_est_monthly_bill`, which is a genuinely different quantity (fixed delivery + monthly EV cost).

---

## 2. What enhancements are possible from the available IONIQ 6 + VF9 entities?

186 vehicle entities exist; the loaded config references a small fraction. These are the ones worth wiring, ordered by value. All are enhancements — none is a defect on its own.

### E1. Vehicle detection ignores six direct charging-state discriminators
**[repo-confirmed]** — [configuration.yaml:781](configuration.yaml:781)

`sensor.ev_charging_vehicle_detected` ([778-802](configuration.yaml:778)) decides which car charged purely by subtracting an `input_number` SoC baseline from current SoC, then tie-breaking on kWh-per-percent against hardcoded 0.774 / 1.23 constants. Six direct discriminators sit in the registry unreferenced: `binary_sensor.ioniq_6_ev_battery_plug`, `binary_sensor.ioniq_6_ev_battery_charge`, `sensor.vf9_..._dong_dien_sac` (Charging Current, A), `sensor.vf9_..._dien_ap_sac` (Charging Voltage, V), `sensor.vf9_..._cong_suat_sac` (Charging Power, kW), `sensor.vf9_..._cong_suat_sac_tinh_toan_live`. Two freshness aids are also unused: `sensor.ioniq_6_last_updated_at` and the writable `button.ioniq_6_force_refresh`. (`sensor.vf9_..._trang_thai_sac` is already a live trigger at [06:390](automations/06_enhancements.yaml:390) and [06:1006](automations/06_enhancements.yaml:1006), so the VF9 half is half-wired.)

**Why it matters.** This is the direct remedy for A8's failure mode: if the IONIQ's cloud poll does not refresh between session start and end, `ioniq_gain` is 0 and the entire session becomes unattributed — or worse, gets billed to the VF9.

**Fix.** Add a layered detector *in front of* the existing logic, never replacing it:
- **Layer 1 (VF9-positive, strongest):** `dong_dien_sac | float(0) > 1` or `cong_suat_sac | float(0) > 0.5` while `binary_sensor.grizzl_e_charging` is on → `vf9`.
- **Layer 2 (IONIQ, freshness-gated):** `is_state('binary_sensor.ioniq_6_ev_battery_plug','on') and is_state('binary_sensor.ioniq_6_ev_battery_charge','on')` AND `sensor.ioniq_6_last_updated_at` less than 900s old → `ioniq_6`.
- **Layer 3:** fall through to the current SoC-delta template unchanged.

Press `button.ioniq_6_force_refresh` as the first action of `ev_session_start_record_soc` ([08:28](automations/08_ev_per_vehicle_cost_tracking.yaml:28)) and wait ~30s before reading baselines. Bonus: a start-of-session discriminator lets the "EV Charging Started" notification at [05:21-27](automations/05_grizzl_e_charging.yaml:21) name the vehicle, which end-of-session delta logic structurally cannot do.

**Two live checks before relying on this.** (a) `sensor.ioniq_6_last_updated_at` has no `device_class` in the registry dump, so its state string may not parse as a timestamp — verify in Developer Tools → Template and wrap the freshness gate in a `| default` guard. (b) Confirm `dong_dien_sac` and `cong_suat_sac_tinh_toan_live` are non-zero mid-session in Developer Tools → States while the VF9 charges.

---

### E2. Off-peak charging is only ever nagged about — the IONIQ is remotely schedulable
**[repo-confirmed]** — [automations/06_enhancements.yaml:595](automations/06_enhancements.yaml:595)

`ev_no_event_offpeak_reminder` ([595-628](automations/06_enhancements.yaml:595)) and `ev_calendar_departure_check` ([556-593](automations/06_enhancements.yaml:556)) only send push notifications telling the user to plug in before the 23:00 ULO window. [grizzl_e_rates.json:8-11](grizzl_e_rates.json:8) shows a 10x spread (3.9¢ overnight vs 39.1¢ on-peak).

Control availability is asymmetric and both halves are unused:
- **Grizzl-E: read-only.** [configuration.yaml:624-684](configuration.yaml:624) defines it purely as `command_line` sensors plus one binary_sensor. There is no switch, select or number for it anywhere. Charger-side scheduling is impossible.
- **IONIQ: writable.** `switch.ioniq_6_ev_charging`, `number.ioniq_6_ac_charging_limit` (%), `number.ioniq_6_dc_charging_limit` (%). Timing input: `sensor.ioniq_6_estimated_charge_duration` (min, read-only).
- **VF9: not controllable.** `sensor.vf9_..._muc_tieu_sac_target` is a **sensor**, not a number, and no VF9 charging switch exists in the dump.

**Cost of doing nothing.** Home at 17:30 on a weekday at 30% SoC, plugged in immediately rather than waiting for the 22:30 notification. Charging runs straight through the 16:00–21:00 on-peak block at 39.1¢. A 40 kWh session that would cost ~$1.56 overnight costs ~$15.64 — about $14 wasted, repeatable several times a week. The existing automations detect the situation perfectly and then do nothing but send a message.

**Fix.** For the IONIQ, build true delayed charging: on `binary_sensor.ioniq_6_ev_battery_plug` turning on during a non-overnight period, `switch.turn_off` on `switch.ioniq_6_ev_charging`, then `switch.turn_on` at 23:00. Make it departure-aware by reading `sensor.ioniq_6_estimated_charge_duration` and starting at `departure_time - duration` so the car is ready but never charges before 23:00. Use `number.set_value` on `number.ioniq_6_ac_charging_limit` to hold 80% on ordinary nights, raising to 100% only when the road-trip detection at [06:630](automations/06_enhancements.yaml:630) fires. For the VF9, state plainly that HA cannot delay or limit its charging — the only options are the in-car scheduler or a switched outlet upstream — and keep the 22:30 nag, surfacing `sensor.vf9_..._thoi_gian_sac_con_lai` in it so the user knows whether a late start still finishes overnight.

---

### E3. The HA Energy dashboard is not configured despite an Energy-ready charger sensor
**[needs live check]** — [configuration.yaml:660](configuration.yaml:660)

`sensor.grizzl_e_total_energy` ([660-668](configuration.yaml:660)) already declares `device_class: energy` and `state_class: total_increasing` — exactly the shape the Energy dashboard needs for an individual device or EV-charger source. But `configuration.yaml` has no `energy:` key and `.storage/energy` is absent from the repo while **not** being gitignored (the .gitignore explicitly excludes many other `.storage` files). That combination suggests energy preferences were never configured.

**Cost of doing nothing.** All the per-period cost work in 06 and 08 is reachable only through the custom dashboard view; none of it appears in HA's native long-term energy statistics, hourly cost breakdown, or the companion app's energy card. Historical data is **not retroactively backfilled** once Energy is finally configured, so every month of delay is a month of statistics permanently missing.

**Fix.** On the Pi: Settings → Dashboards → Energy, add `sensor.grizzl_e_total_energy` under "Individual devices". For per-vehicle attribution, `sensor.ev_ioniq_6_total_energy` and `sensor.ev_vf9_total_energy` ([configuration.yaml:828-838](configuration.yaml:828)) already carry `state_class: total_increasing` and `kWh` but are missing `device_class: energy` — add it to both so they become selectable.

**Correction to a tempting shortcut:** `sensor.solar_energy_month` ([configuration.yaml:613-621](configuration.yaml:613)) is **not** Energy-ready — it has neither `device_class` nor `state_class`, so it has no long-term statistics and cannot be selected as a solar production source at all. Adding both attributes is a prerequisite, not an afterthought.

**Live check first:** `ls -la /opt/homeassistant/.storage/energy` — if it already exists, this is void.

---

### E4. The VF9 independently measures grid-side charging energy — a free cross-check on the Grizzl-E meter
**[repo-confirmed]** — [automations/06_enhancements.yaml:1157](automations/06_enhancements.yaml:1157)

Four VF9 session entities are already consumed by `vf9_charging_session_summary` at [1012-1020](automations/06_enhancements.yaml:1012). Three are not referenced anywhere: `sensor.vf9_..._dien_nang_lay_tu_luoi_lan_cuoi` (Grid Energy Drawn (Last), kWh), `sensor.vf9_..._thoi_gian_cam_sac_lan_cuoi` (Charging Duration (Last), min), `sensor.vf9_..._so_lan_sac_tai_nha` (Home Charging Sessions) — along with `so_lan_sac_tai_tram` and `tong_so_lan_sac`. The grid-side one is the valuable one: it is the car's own measurement of energy pulled from the wall, directly comparable to the Grizzl-E's `session_energy_kwh`.

**Why it matters.** If the Grizzl-E's CT clamp drifts or the daemon's kWh integration accumulates error, *every* downstream number silently inherits it — `sensor.grizzl_e_total_cost`, the ULO period costing, the per-vehicle accumulators, the monthly reconciliation. Nothing in the config can detect this, because every energy figure traces to the same single meter. The VF9 has been independently measuring the same wall energy the whole time and the reading is discarded.

**Fix.** Add a meter-agreement check to `vf9_charging_session_summary` (which already triggers on `trang_thai_sac` leaving 'Charging' at [1006](automations/06_enhancements.yaml:1006)): compare `dien_nang_lay_tu_luoi_lan_cuoi` against `state_attr('sensor.grizzl_e_total_cost','session_energy_kwh')` and alert on >10% divergence for sessions above 5 kWh. Add `thoi_gian_cam_sac_lan_cuoi` to the summary message. Also fix [1167-1172](automations/06_enhancements.yaml:1167) to deliver what the description at [1157](automations/06_enhancements.yaml:1157) promises ("home vs station sessions") by adding `so_lan_sac_tai_nha` and `so_lan_sac_tai_tram`.

**Timing caveat — verify before enabling the alert.** The trigger fires 2 minutes after charging stops ([1008](automations/06_enhancements.yaml:1008)). Whether the Grizzl-E attribute still holds the just-finished session's kWh at that moment, and whether the VF9's `_lan_cuoi` sensors have refreshed by then, is not determinable from this repo. Check `cat /opt/homeassistant/grizzl_e_state.json` immediately after a session ends. If the two are not time-aligned, a 10% check produces false alarms instead of catching drift.

---

### E5. VF9 pack size is a magic number and battery-health monitoring is threshold-only
**[repo-confirmed]** — [automations/06_enhancements.yaml:399](automations/06_enhancements.yaml:399)

[Line 399](automations/06_enhancements.yaml:399) divides by a literal `1.23` and [line 409](automations/06_enhancements.yaml:409) prints "123 kWh pack". `vf9_battery_health_monitor` ([979-995](automations/06_enhancements.yaml:979)) only fires on hard threshold crossings and never trends. Two unused health entities complement the two already used: `sensor.vf9_..._kha_nang_chai_pin_theo_range_tham_khao` (Battery Degradation Potential, %) and `sensor.vf9_..._suc_khoe_pin_soh_tinh_toan` (SOH Calculated, %).

**Fix — trending is the load-bearing half.** Add a monthly notification comparing `suc_khoe_pin_soh` against its value 12 months ago (a `statistics` platform sensor or a monthly `input_number` snapshot), with the two unused entities as corroborating readings. Additionally add a warranty tripwire the integration practically invites: a template `binary_sensor` that alerts when `|suc_khoe_pin_soh - suc_khoe_pin_soh_tinh_toan| > 5` — BMS-reported SOH is notoriously optimistic and only recalibrates after full cycles, so divergence from the back-computed figure is the actual signal. Neither is currently used by any automation.

**A caveat on the obvious refactor.** Substituting `sensor.vf9_..._dung_luong_pin_thiet_ke` ("Battery Capacity (Design)", kWh) for the `1.23` literal is a readability win only — **design capacity is nameplate and does not decline with age**, so it does not fix the degradation drift. If the divisor is to be made degradation-aware, the correct input is design capacity scaled by `suc_khoe_pin_soh`, not the design sensor alone.

**Asymmetry to state honestly:** the IONIQ has **no HV battery SOH entity at all** — kia_uvo exposes none, and `sensor.ioniq_6_car_battery_level` is the 12V accessory battery, not the traction pack. The IONIQ's 0.774 / 77.4 constants at [configuration.yaml:772](configuration.yaml:772), [774](configuration.yaml:774) and [06:369](automations/06_enhancements.yaml:369) genuinely must stay hardcoded. The nearest proxy is trending a *fixed* `sensor.ev_charging_efficiency` (A3) — a persistent rise in kWh-per-percent indicates capacity loss.

---

### E6. The bedtime summary silently locks the IONIQ and never reports plug state; no IONIQ maintenance alerting exists
**[repo-confirmed]** — [automations/01_main.yaml:274](automations/01_main.yaml:274)

The bedtime routine sweeps `states.lock` at [261-266](automations/01_main.yaml:261) and sends `lock.lock` to everything unlocked except `lock.airbnb` — so `lock.ioniq_6_door_lock` is already being commanded implicitly by domain, with no mention in the summary. The summary at [274](automations/01_main.yaml:274) reports only SoC and charger state. `binary_sensor.ioniq_6_ev_battery_plug` — the single fact determining whether overnight charging will actually happen — is unused.

**Failure scenario.** At 23:00 you hear "EV: 34% SoC, not charging. Off-peak starts in now minutes" and go to bed assuming the car will charge on the cheap window. The cable was never seated. You wake to 34% and either skip a trip or fast-charge at on-peak rates.

**Fix — three grouped changes.**
1. At [01_main.yaml:274](automations/01_main.yaml:274), add plug state and the car's lock state so the implicit lock sweep is visible rather than silent:
   ```yaml
   {{ 'plugged in' if is_state('binary_sensor.ioniq_6_ev_battery_plug','on') else 'NOT plugged in' }}
   ```
2. Replace the 24h-staleness guesswork in `ev_phantom_drain_detection` (A13) with direct 12V thresholds — `sensor.ioniq_6_car_battery_level` and `sensor.vf9_..._pin_12v_ac_quy` both report 12V state of charge directly, so the automation is currently guessing at something both cars already measure. Alert below ~60%.
3. Add **one** low-frequency maintenance automation covering exactly four things: `binary_sensor.ioniq_6_tire_pressure_all` turning on (naming corners from the four per-corner sensors, mirroring the VF9 handling at [06:817-855](automations/06_enhancements.yaml:817)); `sensor.ioniq_6_dtc_count` going 0 → above 0; and `sensor.ioniq_6_next_service` minus `sensor.ioniq_6_odometer` falling below 1000 km.

**Naming the noise matters as much as naming the signal.** Do **not** alert on the 12 lamp/headlamp/turn-signal fault sensors, `transmission_condition`, `sleep_mode_check`, `accessory`, `engine`, `defrost`, `steering_wheel_heater`, `remote_ignition`, or the 23 debug/identity entities (`raw_cmd_8`–`raw_cmd_20`, `system_debug_raw`, `hinh_anh_xe_url`, `ten_dinh_danh_xe*`, `phien_ban_*`, `fix_map`, `sensor.ioniq_6_data`). These flap or are static and would train the user to ignore vehicle notifications.

**Adjacent bug while you are in this block:** [automations/01_main.yaml:270](automations/01_main.yaml:270) interpolates `{{ unlocked }}`, a variable never defined anywhere in the automation, so the LLM prompt receives an empty value for the list of locks it is being asked to summarise.

---

### E7. Two preconditioning automations fire on the same trigger with contradictory messages, and neither ever turns climate off
**[repo-confirmed]** — [automations/06_enhancements.yaml:771](automations/06_enhancements.yaml:771)

`ev_climate_precondition_departure` ([767-799](automations/06_enhancements.yaml:767)) and `vf9_climate_precondition` ([1058-1091](automations/06_enhancements.yaml:1058)) share an identical trigger: calendar `calendar.arshad14_gmail_com`, event start, offset -00:20:00, person home, temp <5°C or >28°C. The description at [771-772](automations/06_enhancements.yaml:771) says "VF9 climate control not yet available as a HA entity" and the Echo announcement at [797](automations/06_enhancements.yaml:797) tells the user to "precondition the VF9 manually" — but `button.vf9_..._bat_dieu_hoa` (AC On) exists and is pressed 280 lines later at [1081](automations/06_enhancements.yaml:1081). Separately, `climate.turn_on` at [788](automations/06_enhancements.yaml:788) and the AC-On press at [1081](automations/06_enhancements.yaml:1081) have no counterpart: `button.vf9_..._tat_dieu_hoa` (AC Off, writable) is referenced nowhere, and `switch.ioniq_6_climate` (writable) is also unused.

**Failure scenario.** A calendar event at 08:00 on a -12°C morning. At 07:40 both automations fire. The Echo announces "Your IONIQ 6 is getting ready… Remember to precondition the VF9 manually", then immediately "Preconditioning the VF9" — while the VF9's AC is already running. Following the first announcement, the user starts VF9 climate a second time from the app. Neither automation schedules an off, so if the plan changes and nobody leaves, cabin heat keeps drawing from the pack with no HA-side stop, spending range that was charged at 3.9¢. (The stale "manually" sentence is inside the `{% if temp < 5 %}` branch, so the contradiction only occurs on the cold path.)

**Fix.** (1) Delete the stale clause at [771-772](automations/06_enhancements.yaml:771) and the cold-path sentence at [797](automations/06_enhancements.yaml:797). (2) Merge the two automations into one `choose`, or add mutually exclusive conditions, so only one announcement is produced per event. (3) Add a stop path: `- delay: '00:25:00'` then `button.press` on `button.vf9_..._tat_dieu_hoa` and `climate.turn_off` on `climate.ioniq_6_climate_control`, guarded by a condition that the person is still home. Honest caveat: kia_uvo remote climate normally has a vehicle-side timeout, so the accurate claim is unnecessary drain rather than indefinite runaway — the VF9 button's behaviour is unknown and is the one worth bounding explicitly.

---

### E8. Give the VF9 a home-presence sensor so its automations match the IONIQ's
**[repo-confirmed]** — [automations/06_enhancements.yaml:440](automations/06_enhancements.yaml:440)

`device_tracker.ioniq_6_location` is the only device_tracker in the entire 186-entity dump. The VF9 exposes raw coordinates instead — `sensor.vf9_..._vi_do_latitude` and `sensor.vf9_..._kinh_do_longitude` (both unused), plus `_do_cao_altitude` and `_lo_trinh_gps`. `sensor.vf9_..._vi_tri_xe_dia_chi` is used, but only as a display string at [06:1051](automations/06_enhancements.yaml:1051). This is the structural reason A13's VF9 branch has no location gate.

**Fix.** Add a template binary_sensor in the `template:` block ([configuration.yaml:686](configuration.yaml:686)):

```yaml
      - name: "VF9 Home"
        unique_id: vf9_home
        device_class: presence
        availability: >
          {{ states('sensor.vf9_rllv2cja5rh000847_vi_do_latitude') not in ['unknown','unavailable','']
             and states('sensor.vf9_rllv2cja5rh000847_kinh_do_longitude') not in ['unknown','unavailable',''] }}
        state: >
          {{ distance(states('sensor.vf9_rllv2cja5rh000847_vi_do_latitude') | float(0),
                      states('sensor.vf9_rllv2cja5rh000847_kinh_do_longitude') | float(0)) | float(999) < 0.2 }}
```

Then add `and is_state('binary_sensor.vf9_home','on')` to the `vf9_stale` expression at [06:440](automations/06_enhancements.yaml:440). The `availability:` guard matters — without it, unknown coords parse to 0,0 and the sensor reports "not home" from the middle of the Atlantic. This same sensor also enables "VF9 arrived home" triggers, giving the two vehicles symmetric automations. All source entities are read-only.

**Note:** HA's `template:` integration has no `device_tracker` platform, so use the binary_sensor form above rather than a literal template device_tracker.

---

## 3. Are the entities properly labeled?

Short answer: **no, and the label feature is entirely unused.** There is nothing wrong with most names, but the metadata layer that would make 186 vehicle entities manageable does not exist.

### L1. VF9 VIN is baked into 194+ entity_id references committed to a GitHub remote
**[needs live check]** — [configuration.yaml:782](configuration.yaml:782)

The `vinfast` HACS integration built every one of the VF9's 117 entity_ids as `<domain>.vf9_rllv2cja5rh000847_<slug>`, so the full 17-character VIN is a literal in template code. `git ls-files` confirms all carrier files are tracked: `.storage/core.entity_registry` (117 hits), `.storage/core.device_registry` (device identifier `[['vinfast','RLLV2CJA5RH000847']]`), [automations/06_enhancements.yaml](automations/06_enhancements.yaml) (74 lines), [automations/08_ev_per_vehicle_cost_tracking.yaml:38](automations/08_ev_per_vehicle_cost_tracking.yaml:38), and [configuration.yaml:782](configuration.yaml:782)/[805](configuration.yaml:805)/[812](configuration.yaml:812). `git remote -v` → `git@github.com:arshad1416/HA_Automation_Pi.git`.

The project's own `AGENTS.md` (`CLAUDE.md` is a symlink to it) states the policy: no raw IPs or credentials in Git. The `.gitignore` carefully excludes `.storage/auth`, `core.config_entries`, tokens and keys — but deliberately keeps the entity/device registries tracked "for disaster recovery", which is exactly where the VIN lives. A VIN is not a credential, but it is a globally unique vehicle identifier supporting registration/insurance/recall/theft-history lookup, and it correlates this repo to a physical car at a known address (the config also contains home zone data).

**Failure scenario.** If the repo is public — or ever made public, forked, or mirrored — anyone can `git grep RLLV2CJA5RH000847` and tie the VIN to the rest of the config (automation schedule, occupancy patterns, garage door entities). The Pi's sync cron auto-commits every 15 minutes, so the VIN is re-committed continuously and is already throughout the commit history; a .gitignore rule added today removes nothing from the past.

**Fix.**
1. **Determine exposure first:** `gh repo view arshad1416/HA_Automation_Pi --json visibility`. If public, make it private — that is the only fast mitigation.
2. Do **not** try to fix this by renaming entity_ids (see L2 — the vendored digital-twin card would break).
3. The durable fix is a history scrub (`git filter-repo --replace-text`) with the Pi cron stopped, then push and re-clone on the Pi. Note the sync script does **not** force-push — [git-sync.sh:56](git-sync.sh:56) is a plain `git push` after `git pull --rebase --autostash`, with `--no-verify` on the *commit* at [line 50](git-sync.sh:50) — so a rewrite is less fragile than it first appears, but still needs the cron paused.
4. If a rewrite is out of scope, at minimum stop tracking `.storage/core.entity_registry` and `.storage/core.device_registry` (`git rm --cached`). That stops future VIN-bearing registry churn; the 76 hardcoded references in YAML remain.

For relative priority: this repo already tracks `lutron_caseta-067f6f6f-key.pem` (confirmed in `git ls-files`), so the VIN is not the strongest exposure here.

---

### L2. 93 of 117 VF9 entity_ids ignore the English `suggested_object_id` the integration supplied — but renaming would break the vendored card
**[repo-confirmed]** — [.storage/core.entity_registry:1737](.storage/core.entity_registry:1737)

Every VF9 registry entry carries both a Vietnamese `entity_id` and an English `suggested_object_id`. Registry line 1737: `entity_id: sensor.vf9_rllv2cja5rh000847_nhiet_do_ngoai_troi`, `suggested_object_id: vf9_rllv2cja5rh000847_outside_temperature`, `original_name: "Outside Temperature"`. Counted programmatically: **93 of 117** VF9 entities have `entity_id != suggested_object_id`. The IONIQ 6's 69 entities have no such mismatch.

That pins the mechanism: the entities were first registered by an older build of the integration that named them in Vietnamese; entity_ids are sticky, so a later build that translated names and started emitting English suggestions could not retroactively rename. It also explains the `_2` collision in [Q4/T1](#t1-two-vf9-sensors-are-both-named-outside-temperature-and-both-are-voice-exposed).

Also on the "properly labeled" question: **95 of 117 VF9 entities have `has_entity_name: false`**, so their friendly names carry no "VF9" device prefix (22 do have it and behave normally), while all 69 IONIQ 6 entities have `has_entity_name: true` and get one. And `aliases` is `[]` on **all 186** vehicle entities — zero voice aliases are defined anywhere.

**Failure scenario (developer ergonomics, not runtime).** Writing or debugging any template requires knowing that "Charging Power" is `cong_suat_sac`, "Remaining Range" is `quang_duong_con_lai_theo_hieu_suat`, and "SoC at Plug-in" is `pin_luc_cam_sac_lan_cuoi`. The author already had to paper over this with a translation comment block at [automations/06_enhancements.yaml:10](automations/06_enhancements.yaml:10). One transposed character in a 40-char VIN-bearing slug silently yields `unknown` from `states()` rather than an error, because every call site wraps it in `| default(0, true) | float(0)`. A14 is exactly this failure realised.

**Fix — do NOT mass-rename.** `custom_components/vinfast/vinfast-digital-twin.js` builds entity_ids at runtime by string concatenation (line 295 `sensor.${p}_${suffix}`, line 854, line 156) across **60 distinct hardcoded Vietnamese suffixes**. A mass rename silently blanks that entire Lovelace card, and being vendored, any edit is lost on the next HACS update. Use the two layers that do not move the entity_id:
1. **Add registry aliases** (currently `[]` on all 186) for the ~10 entities you actually speak to: Settings → Entities → entity → Voice assistants → Aliases. This fixes voice without touching entity_ids.
2. **Wrap the handful used in templates behind clearly-named template sensors** so future automations reference readable ids.

If you rename anyway, the full lockstep blast radius is [configuration.yaml:782](configuration.yaml:782)/[805](configuration.yaml:805)/[812](configuration.yaml:812), [08:38](automations/08_ev_per_vehicle_cost_tracking.yaml:38), 74 lines in [06_enhancements.yaml](automations/06_enhancements.yaml), plus a fork of the vendored JS card. That is why aliasing is the recommendation.

---

### L3. `sensor.ioniq_6` has no name of any kind and renders as the bare device name "IONIQ 6"
**[needs live check]** — [.storage/core.entity_registry:1269](.storage/core.entity_registry:1269)

Registry row 1269: `name: null`, `original_name: null`, `has_entity_name: true`, `translation_key: "engine_type"`, `entity_category: "diagnostic"`. It is the only one of the 186 vehicle entities with a null effective name. Traced: `custom_components/kia_uvo/sensor.py:294-299` declares the description with no `name=`, `grep -n '_attr_name'` over that file returns nothing, and `engine_type` is **not** among the 60 keys under `entity.sensor` in `custom_components/kia_uvo/translations/en.json` (nor in `strings.json`). With `has_entity_name: true` and no resolvable entity name, HA falls back to the device name alone.

**Failure scenario.** The sensor appears as "IONIQ 6" — byte-identical to the device it belongs to — among 68 properly-named siblings, and a user cannot tell what it reports (the powertrain type string, e.g. `EV`). Searching "IONIQ 6" in the entity picker surfaces it above the sensors actually wanted. Being `entity_category: diagnostic` it is excluded from voice exposure, so this is UI legibility only.

**Fix.** Registry name override: Settings → Devices & Services → Entities → `sensor.ioniq_6` → rename to "Engine Type". With `has_entity_name: true` that renders "IONIQ 6 Engine Type", matching every sibling, and survives HACS updates — unlike patching the vendored translation file, which `AGENTS.md` forbids and which is overwritten on update. Renaming the entity_id to `sensor.ioniq_6_engine_type` is also safe here (unlike L2): `git grep 'sensor\.ioniq_6\b'` finds no references in configuration.yaml, automations/, dashboards/, scripts.yaml or scenes.yaml. Worth an upstream issue against kia_uvo to add the missing string.

**Live check:** Developer Tools → Template → `{{ state_attr('sensor.ioniq_6','friendly_name') }}` — expect "IONIQ 6" with no entity name appended.

---

### L4. One VF9 entity is left with an untranslated Vietnamese friendly name — and it is the 12V battery
**[repo-confirmed]** — [.storage/core.entity_registry:1777](.storage/core.entity_registry:1777)

Scanning `original_name`/`name` on all 186 vehicle entities for Vietnamese diacritics returns exactly one hit: `sensor.vf9_rllv2cja5rh000847_pin_12v_ac_quy` with `original_name: "Pin 12V (Ắc quy)"`, unit `%`. The registry shows the integration never translated it rather than a user override: `name: null`, and unusually its `suggested_object_id` is **also** Vietnamese, whereas the other 116 all supply an English one.

**Failure scenario.** A user scanning the VF9 device page or searching for "12V" or "auxiliary battery" either does not recognise it or cannot type the diacritics into the search box. Since the 12V accessory battery going flat is the single most common thing that bricks an EV's ability to wake and report, this is the entity most worth having findable and alertable — and it is currently the least findable on the device. No automation watches it today.

**Fix.** Registry name override to "12V Auxiliary Battery" (Settings → Entities). Do not edit the vendored translation files; do not delete the entity, it will be recreated. **Worth doing at the same time:** add a low-12V alert alongside the existing VF9 automations — a drop below ~60% is the standard early warning before the car stops responding to remote commands (this is also part of the E6 fix).

**One blast-radius correction:** `custom_components/vinfast/vinfast-digital-twin.js:1079` does reference `pin_12v_ac_quy`. It resolves by entity_id suffix, so a friendly-name override leaves it untouched — but "nothing references this entity" would be inaccurate.

---

### L5. *(enhancement)* Zero HA labels exist, and the IONIQ 6 device has no area
**[repo-confirmed]** — [.storage/core.device_registry:297](.storage/core.device_registry:297)

On labels specifically: `.storage/core.label_registry` **does not exist**, and all 3002 `"labels"` arrays across `core.entity_registry` and `core.device_registry` are `[]`. **Zero labels are defined anywhere in this installation.**

On areas, the two vehicles are inconsistent:
- IONIQ 6, device `81cb37f577495ac7b13a9404b896222f` ([.storage/core.device_registry:297](.storage/core.device_registry:297)): `area_id: null`. All 69 of its entities are also `area_id: null`, so they inherit nothing.
- VF9 BLIBS, device `710062a01ac8dbb167fd687c702e35df` ([.storage/core.device_registry:337](.storage/core.device_registry:337)): `area_id: "outdoor"`.

The EV helper layer has no grouping at all: the eight EV `input_number` helpers at [configuration.yaml:275-337](configuration.yaml:275) and `input_text.ev_session_vehicle` at [configuration.yaml:432](configuration.yaml:432) are YAML-defined, hence area-less, label-less and device-less. The 15 template sensors at [configuration.yaml:725-844](configuration.yaml:725) likewise.

**Consequence.** There is no way to write `target: {label_id: ev}` or an area target to hit the EV fleet. Every automation must enumerate entity_ids by hand — which is precisely what `06_enhancements.yaml` does across 74 VIN-bearing lines. Adding a third vehicle would mean hand-editing every one of those lists. Area-scoped voice queries also behave inconsistently between the two cars, which reads as a broken integration rather than a config gap.

**Fix — pure UI/registry work, no YAML and no restart.**
1. Settings → Areas, labels & zones → Labels → create `ev`, `ev-charging`, `vehicle`. Apply `vehicle` to both vehicle devices (labels inherit to their 186 entities), and `ev-charging` to the 5 Grizzl-E command_line sensors, the 8 Grizzl-E utility_meters ([configuration.yaml:874-912](configuration.yaml:874)) and the 8 input_number helpers.
2. Assign the IONIQ 6 device an area matching the VF9 so area-scoped queries behave identically for both cars.

**Blast radius: none.** Labels and areas are additive registry metadata; nothing in this repo references a label_id or an area for these entities, so nothing can break. Note the registries are git-tracked, so this shows up as a `.storage/` diff on the next sync.

---

## 4. Duplicate labels, or entities reporting the same thing

There are **no duplicate labels** — see L5, zero labels exist. On duplicate *entities*: across all 1861 registry entities I grouped by effective display name (name override if set, else original_name, prefixed by device name when `has_entity_name` is true), yielding 74 collisions config-wide, of which **exactly one** involves a vehicle entity. Separately, one genuine duplicate template sensor exists in the EV config. Most apparent VF9 redundancy is deliberate.

### T1. Two VF9 sensors are both named "Outside Temperature" and both are voice-exposed
**[repo-confirmed]** — [.storage/core.entity_registry:1779](.storage/core.entity_registry:1779)

- `sensor.vf9_rllv2cja5rh000847_nhiet_do_ngoai_troi` (registry line 1737), unique_id `vf9_rllv2cja5rh000847_api_outside_temp`
- `sensor.vf9_rllv2cja5rh000847_nhiet_do_ngoai_troi_2` (registry line 1779), unique_id `vf9_rllv2cja5rh000847_34183_00001_00007`

Both have `original_name: "Outside Temperature"`, `name: null`, unit `°C`, `original_device_class: temperature`, `has_entity_name: false` (so **no device prefix disambiguates them** — the friendly name is literally "Outside Temperature" for both), and critically both carry `options.conversation.should_expose: true`. They are 2 of only 3 VF9 entities exposed to voice at all (VF9: 3 exposed / 114 not. IONIQ 6: 11 / 56).

The unique_ids pin the root cause: `api_*` = the integration's cloud-API-derived field; `34183_00001_00007` = a raw telemetry signal channel. Both requested the same `suggested_object_id`, which is why the second got the `_2` suffix.

**Failure scenario.** In every entity picker, search box, and history card the user sees two indistinguishable "Outside Temperature" rows and cannot tell which one a dashboard card is bound to — that half is deterministic from the registry. For voice, asking "what is the outside temperature" matches two entities with byte-identical names and no device prefix to break the tie, so the query will not reliably return the intended sensor. (I could not verify HA's exact resolution behaviour for ambiguous names from this machine — do not assume it silently flips versus rejecting the match.)

**Explicitly not collisions, so you don't chase them:** `Defrost`, `Hood`, `Odometer` and `Trunk` each appear on both vehicles, but the IONIQ 6 entities have `has_entity_name: true` and render as "IONIQ 6 Odometer" etc. These resolve correctly and need no action.

**Fix.** Entity registry only — no YAML. Rename the API one to "Outside Temperature (API)" and the telemetry one to "Outside Temperature (Vehicle)", and set `Expose to Assist` = off on whichever you consider secondary. **Do not delete** — both are `vinfast` platform entities and will be recreated on the next integration reload.

**Which is the keeper is not decidable from the repo — pick by freshness.** Developer Tools → Template:
```
{{ states('sensor.vf9_rllv2cja5rh000847_nhiet_do_ngoai_troi') }} @ {{ states.sensor.vf9_rllv2cja5rh000847_nhiet_do_ngoai_troi.last_updated }}
{{ states('sensor.vf9_rllv2cja5rh000847_nhiet_do_ngoai_troi_2') }} @ {{ states.sensor.vf9_rllv2cja5rh000847_nhiet_do_ngoai_troi_2.last_updated }}
```
Keep whichever `last_updated` advances while the car is awake. Weak prior: the raw telemetry one (`_2`) is the live signal and `api_outside_temp` is a status-payload copy that can be stale.

**Blast radius: zero.** `git grep nhiet_do_ngoai_troi` over loaded config returns nothing in configuration.yaml, automations/, scripts.yaml, scenes.yaml or dashboards/. The only other reference is `custom_components/vinfast/vinfast-digital-twin.js:895`, which reads a *different* slug (`nhiet_do_ngoai_troi_gps`).

---

### T2. `sensor.monthly_ev_charging_cost` is a zero-consumer passthrough of `sensor.grizzl_e_cost_monthly`
**[repo-confirmed]** — [configuration.yaml:748](configuration.yaml:748)

[configuration.yaml:746-751](configuration.yaml:746) defines a template sensor whose entire state is `{{ states('sensor.grizzl_e_cost_monthly') | float(0) | round(2) }}`. The source is a real `utility_meter` at [configuration.yaml:904-907](configuration.yaml:904). The template adds nothing — no unit change, no offset, no availability gate, no attributes. It only rounds to 2dp, which `suggested_display_precision` already handles for a monetary sensor.

This is the only pure-passthrough in the EV config. The other three `state: "{{ states(...` one-liners ([744](configuration.yaml:744), [832](configuration.yaml:832), [838](configuration.yaml:838)) all convert an `input_number` into a `sensor` with a `state_class`, which is a required bridge because `utility_meter` cannot take an `input_number` as a source — those are legitimate.

**It has no consumers.** `git grep monthly_ev_charging_cost` returns exactly two hits: its own definition and its orphan registry row at `.storage/core.entity_registry:1631`. It is absent from the dashboard, all seven loaded automation files, scripts.yaml and scenes.yaml. No UI-mode dashboard could hide a reference either: `.storage/lovelace_dashboards` lists exactly one storage-mode dashboard (`map`), whose config is just `{strategy: {type: map}}`.

**Failure scenario.** Two entities named "Monthly EV Charging Cost" and "Grizzl-E Cost Monthly" hold the identical number, so any future card or automation has a coin-flip chance of binding to the wrong one — and the duplicate is strictly the worse target. `sensor.grizzl_e_cost_monthly` is a utility_meter with `state_class: total` and proper long-term statistics ([dashboards/ev-charging.yaml:44](dashboards/ev-charging.yaml:44) uses it); the passthrough declares no `state_class` at all, so it is silently excluded from the Energy dashboard and from `statistics-graph` cards. A user who picks it by name gets an empty graph with no error.

**Contrast, keep this one:** `sensor.grizzl_e_est_monthly_bill` ([configuration.yaml:725-731](configuration.yaml:725)) reads the same source but **adds** `fixed_monthly_cad` — genuinely distinct, and used at [dashboards/ev-charging.yaml:51](dashboards/ev-charging.yaml:51).

**Fix.** Delete [configuration.yaml:745-751](configuration.yaml:745). After the reload the entity goes `unavailable` and lingers, so also remove it via Settings → Entities → delete. Anything that later wants this number should use `sensor.grizzl_e_cost_monthly` directly.

---

### T3. Four VNĐ-denominated VF9 cost sensors overlap with the CAD Grizzl-E figures
**[needs live check]** — [automations/06_enhancements.yaml:1179](automations/06_enhancements.yaml:1179)

Four VF9 sensors carry `unit_of_measurement: "VNĐ"` and `device_class: monetary` in the registry: `tong_chi_phi_sac_quy_doi` (Total Charging Cost, registry line 1726), `chi_phi_sac_chuyen_di` (Trip Charging Cost), `tong_chi_phi_xang_tuong_duong` (Equivalent Gasoline Cost), `chi_phi_xang_chuyen_di` (Trip Gasoline Cost). Two loaded automations render them into push notifications: [06:1019](automations/06_enhancements.yaml:1019) interpolates two of them bare, and [06:1168-1179](automations/06_enhancements.yaml:1168) computes `Savings: {{ (gas_equiv - total_cost) | round(2) }}`.

**To be precise about what is and is not wrong:** the arithmetic at [1179](automations/06_enhancements.yaml:1179) is *sound* — both operands are VNĐ, so it is same-currency subtraction. There is no cross-currency arithmetic anywhere in this config. The defect is an unlabelled foreign-currency figure delivered to a Canadian household, alongside `sensor.grizzl_e_cost_monthly` which is the authoritative CAD number for the same concept ([dashboards/ev-charging.yaml:44](dashboards/ev-charging.yaml:44)). Two contradictory "total charging cost" figures circulate.

**Fix.** (1) In [06_enhancements.yaml](automations/06_enhancements.yaml), either drop the four VNĐ variables from the two notification bodies, or convert and label them — define the FX rate as an `input_number` rather than a magic literal and append the unit. (2) **Hide, do not delete**, the four sensors in the registry (Visible = off). They are `vinfast` platform entities and will be recreated on the next update; hiding also keeps a foreign-currency `device_class: monetary` sensor out of the Energy dashboard's monetary pickers, which is a live foot-gun. Hidden entities still have state, so nothing breaks.

**Blast radius:** `tong_chi_phi_sac_quy_doi` → [06:1019](automations/06_enhancements.yaml:1019), [06:1168](automations/06_enhancements.yaml:1168), plus vendored `vinfast-digital-twin.js:1188` (which correctly appends "VNĐ" itself — leave it, it's honest). `chi_phi_sac_chuyen_di` → [06:1018](automations/06_enhancements.yaml:1018), [06:1169](automations/06_enhancements.yaml:1169). `tong_chi_phi_xang_tuong_duong` → [06:1171](automations/06_enhancements.yaml:1171). No dashboard or configuration.yaml references.

**Live check:** Settings → Devices & Services → VinFast → Configure — read the configured electricity price and gas price. The integration defaults are 4000 and 20000 (`api.py:197-198`), but `.storage/core.config_entries` is gitignored so the actual values are unknown from here.

---

### T4. *(enhancement)* `sensor.grizzl_e_diagnostics` duplicates `power_w` and `rssi_dbm`, and both copies are unread
**[repo-confirmed]** — [configuration.yaml:657](configuration.yaml:657)

Two command_line sensors read the same `/config/grizzl_e_state.json` and publish overlapping attributes:
- `sensor.grizzl_e_power` ([configuration.yaml:625-637](configuration.yaml:625)): state = `power_w`, `json_attributes: [charging, rssi_dbm, updated]`, scan_interval 15s.
- `sensor.grizzl_e_diagnostics` ([configuration.yaml:647-658](configuration.yaml:647)): state = `free_heap`, `json_attributes: [disk_free_kb, rssi_dbm, power_w, updated]`, scan_interval 60s.

So `power_w` is the state of one and an attribute of the other, and `rssi_dbm` is an attribute of both — sampled 15s vs 60s, so the two copies disagree for up to 45 seconds after any change. Nobody uses the diagnostics copies: [dashboards/ev-charging.yaml:111](dashboards/ev-charging.yaml:111) binds `grizzl_e_diagnostics` for "Free Heap" only, and [114-117](dashboards/ev-charging.yaml:114) deliberately pulls RSSI from `grizzl_e_power`'s attribute instead.

**No current misbehaviour.** The exposure is future: someone adding a charger-health automation picks `state_attr('sensor.grizzl_e_diagnostics','power_w')` because it is the sensor named "diagnostics", and gets a value up to 60s stale — where the existing automations at [06:473](automations/06_enhancements.yaml:473), [477](automations/06_enhancements.yaml:477), [681](automations/06_enhancements.yaml:681), [690](automations/06_enhancements.yaml:690) all correctly use the 15s sensor. A 60s-stale reading defeats the stuck-charger check at [06:481](automations/06_enhancements.yaml:481) ("Vehicle reports 100% SoC but Grizzl-E still drawing …W"), which is exactly a freshness-sensitive comparison.

**Fix.** Delete [configuration.yaml:656](configuration.yaml:656) (`- rssi_dbm`) and [657](configuration.yaml:657) (`- power_w`) from the `json_attributes` of `grizzl_e_diagnostics`, leaving `disk_free_kb` and `updated`. That makes the sensor mean one thing (heap + disk) and leaves one authoritative source for power and RSSI. Blast radius zero — the only consumer reads the sensor's state, not either attribute. Validate any field-name change against the live Pi copy first, since the JSON's producer is not in this repo (A2).

---

### T5. *(enhancement)* DO NOT DEDUPE — three VF9 sensor families are deliberate cross-checks
**[repo-confirmed]** — [.storage/core.entity_registry:1711](.storage/core.entity_registry:1711)

Recorded so a future cleanup does not delete working cross-checks. The `unique_id` prefix is the discriminator and it is unambiguous: `api_*` = derived by the integration from VinFast cloud charge/trip history; `34xxx_xxxxx_xxxxx` = a raw vehicle telemetry channel. Same-sounding names, different provenance.

1. **Battery health.** `suc_khoe_pin_soh` (uid `34220_00001_00001`) is the BMS's own SOH off the telemetry bus. `suc_khoe_pin_soh_tinh_toan` (uid `api_soh_calculated`, registry line 1711) is back-computed from observed charge sessions against design capacity. BMS SOH is optimistic and only recalibrates after full cycles; the derived figure is the independent check. **Divergence between them is the signal** (see E5).
2. **Charging power — three different quantities.** `cong_suat_sac` (uid `34183_00000_00012`) is instantaneous telemetry. `cong_suat_sac_tinh_toan_live` (uid `api_live_charge_power`) is derived from ΔSoC×capacity/Δt and survives telemetry dropouts when the raw channel reads 0. `cong_suat_sac_trung_binh_lan_cuoi` (uid `api_last_charge_power`) is a completed-session average — a historical scalar, already consumed at [06:1016](automations/06_enhancements.yaml:1016).
3. **Range — four distinct concepts.** `quang_duong_du_kien` (uid `34180_00001_00007`) is the dash guess-o-meter. `quang_duong_con_lai_theo_hieu_suat` (uid `api_calc_remain_range`) is recomputed from measured kWh/100km. `quang_duong_cong_bo_max` (uid `api_static_range`) is a manufacturer spec **constant**. `quang_duong_thuc_te_day_100_pin` (uid `api_calc_max_range`) is observed full-charge range.

Same logic for `dien_nang_sac_tai_nha` (car-side kWh) versus the Grizzl-E utility_meter (charger-side, CAD): an independent second source, not a duplicate — the two differ by AC/DC conversion loss, which is exactly the cross-check E4 proposes building.

**Failure scenario if ignored.** A dedupe pass grouping by name similarity flags the SOH pair and the three "Charging Power" variants as redundant and deletes one of each. Deleting the `api_*` member removes the only independent check on BMS-reported health. And because these are HACS platform entities, a delete is silently undone on the next integration update — leaving the config in a state where entities the user believed removed have reappeared with `_2` suffixes, manufacturing exactly the collision documented in T1.

**Fix: no change.** If the device page feels cluttered, use `entity_category: diagnostic` or per-entity Visible = off (reversible, keeps state available to templates), never delete. Before hiding any member of these families, check the unique_id prefix and keep at least one `api_*` and one `34xxx_*` member of each pair.

*(One dependency claim I could not confirm in the vendored source: that deleting `api_static_range` would blank `kha_nang_chai_pin_theo_range_tham_khao`. Treat it as plausible, not proven — it does not change the "don't delete" conclusion.)*

---

### Dedup decision table

| Entity | Verdict | Action | Blast radius |
|---|---|---|---|
| `sensor.vf9_..._nhiet_do_ngoai_troi` vs `..._nhiet_do_ngoai_troi_2` | **True duplicate** (same name, unit, device_class; API copy vs raw telemetry) | Rename both with a source suffix; un-expose the loser from Assist. Do NOT delete — HACS recreates. Pick keeper by `last_updated` freshness | **Zero** — no references in any loaded file; the JS card reads a different slug |
| `sensor.monthly_ev_charging_cost` | **True duplicate** — pure passthrough of `sensor.grizzl_e_cost_monthly`, adds nothing, no `state_class` | Delete [configuration.yaml:745-751](configuration.yaml:745), then delete the orphaned registry row | **Zero** — grep finds only its own definition and its registry row; single storage-mode dashboard is `map` |
| `sensor.grizzl_e_diagnostics` attrs `power_w`, `rssi_dbm` | **Overlapping** — same fields as `sensor.grizzl_e_power` at 4x the scan interval | Delete [configuration.yaml:656-657](configuration.yaml:656); leave `disk_free_kb`, `updated` | **Zero** — the only consumer reads the sensor's state (free_heap), not either attribute |
| 4x VF9 VNĐ cost sensors | **Overlapping / wrong-currency** — restate `grizzl_e_cost_monthly`'s concept in dong | Hide in registry (not delete); strip or convert+label in [06:1019](automations/06_enhancements.yaml:1019) and [06:1168-1179](automations/06_enhancements.yaml:1168) | Two notification bodies; vendored JS card labels them honestly and is unaffected |
| `suc_khoe_pin_soh` vs `suc_khoe_pin_soh_tinh_toan` | **Keep both — cross-check** (BMS-reported vs back-computed) | Keep both; add a divergence >5% tripwire (E5) | N/A — deleting either removes the only independent health check |
| `cong_suat_sac` / `_tinh_toan_live` / `_trung_binh_lan_cuoi` | **Keep all three** — instantaneous / dropout-resilient derived / completed-session average | No change | `_trung_binh_lan_cuoi` is consumed at [06:1016](automations/06_enhancements.yaml:1016) |
| 4x VF9 range sensors | **Keep all four** — guess-o-meter / efficiency-derived / spec constant / observed max | No change | Possible internal dependency on `api_static_range` (unconfirmed) |
| `dien_nang_sac_tai_nha` vs Grizzl-E utility_meter | **Keep both — cross-check** (car-side vs charger-side; differ by AC/DC loss) | Keep both; build the meter-agreement alert in E4 — but use `_dien_nang_lay_tu_luoi_lan_cuoi` for per-session (A4) | `dien_nang_sac_tai_nha` is currently misused as session energy in three places |
| `Defrost` / `Hood` / `Odometer` / `Trunk` on both vehicles | **Not a collision** — IONIQ entities have `has_entity_name: true` so they render device-prefixed | No change | N/A |
| 8x per-vehicle utility_meters (no `unique_id`) | **Not duplicates** — registry-absent, not redundant | Add `unique_id:` per D6 | 8 dashboard rows if the generated entity_id changes |

---

## Recommended order of work

**Tier 1 — data integrity, do first.** These either lose data or corrupt attribution.

1. **A2** — recover `grizzl_e_daemon.py` (`git show 2d783a2:grizzl_e_daemon.py`), commit it and the systemd unit, back up `grizzl_e_history.json`. Do this *first*: it is git-only, needs no HA change, and until it is done a Pi failure is unrecoverable.
2. **A1** — remove `initial:` from the nine EV helpers, then **A17** in the same edit (raise both `max` values to 1000000, since removing `initial:` is what makes the ceiling reachable). Seed the accumulators by hand afterwards.
3. **A5, A7, A6, A14** — the four VF9 automation defects that produce false alerts or silent gaps. A5 (Echo announcements on every lock) and A7 (tire spam) are the ones the household actually notices; A14 is a one-token change.
4. **A3** — fix the efficiency divisor before anyone puts that sensor on a dashboard.
5. **A4** — swap the VF9 lifetime accumulator for the per-session grid-energy sensor.

**Tier 2 — attribution correctness.** A8 (force-refresh before reading SoC) and A10 (guard the baseline recorder) together fix most of the unattributed-cost problem. A9 and A18 fix the monthly reconciliation. E1 is the structural version of the same fix and is worth doing right after A8 rather than later.

**Tier 3 — dashboard.** D1 (`type: attribute`) is a 7-line change that repairs the most-used card. D2, D3, D6, then D4/D5. D7/D8 once A3 is fixed.

**Tier 4 — labels and dedup.** L5 (create labels, give the IONIQ an area), T1, T2, L3, L4, T4. All low-risk, several are pure registry work.

**Tier 5 — enhancements.** E2 (off-peak scheduling) has the largest dollar value of anything in this report — roughly $14 per mistimed session. E3 (Energy dashboard) is time-sensitive only because history is not backfilled. Then E4, E6, E8, E5, E7.

**Housekeeping alongside:** A15 (`preflight.sh` must not report OK when it cannot check), A22 (`entities.md` corrections), A11/A12/A13/A16/A19/A20/A21 as you touch the surrounding files. L1 requires deciding repo visibility first — run `gh repo view arshad1416/HA_Automation_Pi --json visibility` before anything else in that thread.

### Restart vs reload

| Change | Requires |
|---|---|
| `input_number` / `input_text` blocks (A1, A17) | **Full HA restart** — removing `initial:` only takes effect when the entity is freshly added; a YAML reload calls `async_update_config` on surviving entities |
| `template:` sensors (A3, E8), `command_line` sensors (T4), `utility_meter` (D6) | **Full HA restart** — `command_line` and `utility_meter` have no reload service; template sensors do, but mixed edits in `configuration.yaml` are simpler to restart |
| `automations/*.yaml` (A4–A7, A9–A14, A16, A18–A21, A23, A24) | **Reload automations** (Developer Tools → YAML → Automations) |
| `dashboards/ev-charging.yaml` (D1–D5, D7, D8) | **Browser refresh only** — YAML-mode dashboards reload on page load |
| Labels, areas, entity renames, hide/expose (L3, L4, L5, T1, T3-part-2) | **None** — registry writes apply immediately |
| `verification/preflight.sh`, `reference/entities.md`, docs (A15, A22, A2) | **None** — not read by HA |

### Deployment

Nothing in this report has been applied. Per `AGENTS.md`, **any SSH or deploy action against the Pi requires your explicit approval**, and the sequence is fixed:

1. Edit curated files in the Mac clone.
2. `verification/preflight.sh` — and note A15: if it prints `SKIP: PyYAML not installed`, its "preflight OK" means nothing. Fix A15 first or install PyYAML before trusting it.
3. `ssh pi-lan` (LAN) or `ssh pi` (Tailscale) — **with approval**.
4. `docker exec homeassistant python -m homeassistant --script check_config --config /config` — **before** any restart. Mandatory, not optional.
5. Only after check_config passes: reload or restart per the table above.
6. `verification/smoke-tests.sh`.

Remember `main` moves every 15 minutes via the Pi's sync cron — `git fetch && git rebase origin/main` immediately before every push, and expect to retry on a race. Registry changes made in the HA UI (L3, L4, L5, T1) will appear as a `.storage/` diff pushed automatically by that cron; do not also commit them from the Mac clone.
