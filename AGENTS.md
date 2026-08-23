# AGENTS.md — HA_Automation_Pi

Home Assistant configuration for the Raspberry Pi 5. The **live copy is `/opt/homeassistant` on the Pi** (HA runs there in Docker, container name `homeassistant`); Mac clones are mirrors for editing. This file is the routing map for AI agents — follow the pointers instead of duplicating docs.

## File boundaries

**Curated — safe to edit:**

- `configuration.yaml` — core config. Automations load from `automations/` via `!include_dir_merge_list`; `scripts.yaml` and `scenes.yaml` via `!include`.
- `automations/*.yaml`, `scenes.yaml`, `scripts.yaml`, `dashboards/`, `blueprints/`, `esphome/` (curated ESPHome YAML — live configs with real WiFi credentials stay on the Pi and are never committed)
- Root Python daemons: `grizzl_e_daemon.py`, `tuya_kitchen_bridge.py`, `tuya_listener.py`, `update_kitchen_presence.py`, `check_garage_vision.py`
- `scripts/`, `pi-config/`, `verification/`, `grizzl_e_rates.json` (electricity rate config)

⚠️ Root `automations.yaml` is **legacy and NOT loaded** — `configuration.yaml` only includes the `automations/` directory. Do not edit it expecting any effect.

**Vendored — do not edit:** `custom_components/` (HACS-managed integrations; local edits are lost on update).

**Machine-generated — never hand-edit:** `.storage/`, `*_state.json`, `*_history.json`, discovery logs/caches. Never edit `.storage/` files while the container is running (`docker stop homeassistant` first). Volatile state is gitignored; the `.storage/` registries that remain tracked (entity/device/area, person, lovelace, exposed_entities, …) are kept **for disaster recovery only**.

## Change workflow

1. Edit curated files.
2. Run `verification/preflight.sh` — syntax-checks Python daemons and curated YAML before anything ships.
3. Deploy to the Pi (`ssh pi-lan` on LAN, `ssh pi` via Tailscale). Read-only SSH — querying state, reading logs, `docker inspect` — is pre-approved. **Deploying files or restarting/reloading anything (HA container, systemd units) requires explicit user approval.**
4. Validate on the Pi **before** restarting:
   `docker exec homeassistant python -m homeassistant --script check_config --config /config`
5. Only after check_config passes: reload/restart HA, then run `verification/smoke-tests.sh`.

## Sync architecture (read before pushing)

A cron on the Pi runs `git-sync.sh` every 15 min (at :02/:17/:32/:47), auto-committing and pushing the live config straight to `origin/main` with `--no-verify`.

- `main` moves constantly — `git fetch && git rebase origin/main` immediately before every push, and expect to retry on a race.
- Changes made directly on the Pi are captured automatically; do not duplicate them from a Mac clone.
- Do not `git add -f` ignored state files, and do not create `*.bak` copies — git history is the backup.

## Docs

- `README.md` — architecture overview
- `plan.md` — setup commands and system plan
- `walkthrough.md` — narrative walkthrough
- `reference/entities.md` — entity reference
- `reference/climate-setpoint-override.md` — **read before debugging "the AC is not cooling".** The ecobee can run a different setpoint than the one we write (utility demand-response `touSetback`), and `climate.ecobee_3` reports the *requested* value while `climate.ecobee` reports the *effective* one. Also documents the per-room sensor suffix map and the stuck-at-0 sensor failure mode.
