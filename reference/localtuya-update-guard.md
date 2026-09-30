# LocalTuya update guard

Deployment status: service installation/enablement was confirmed. Final live acceptance and the latest low-level/deferred-error safeguards remain pending while Pi access is unavailable. See the dated acceptance audit for the deployed versus local version distinction.

Owner approved the reviewed design/activation scope by instructing “continue” on 2026-09-30. This is a scoped exception to the vendor-file/restart rules: only the exact two audited payload regressions may be automatically repaired. No other vendor changes are authorized.

The Pi service `localtuya-update-guard.service` runs as arshad14 from `/opt/homeassistant/scripts/localtuya_update_guard.py`, with a process lock and 15-second polls. It fingerprints all LocalTuya Python/JSON files, waits 120 seconds of stable bytes and waits while an HA update entity reports a download in progress. It detects a same-version reinstall as well as a changed version. If HACS exposes no LocalTuya update entity, the stable-file check remains the trigger; no file observer can guarantee a downloader will never resume after a long pause.

`localtuya_guard_source.py` recognizes the old/fixed AST of `LocalTuyaLight.async_turn_on` and `TuyaProtocol._generate_payload`, the audited payload templates and constants. Fingerprints normalize syntax-neutral Python-version differences. Unknown changes block automatic repairs and vendor-code execution. The six offline regressions execute only recognized methods in an isolated fixture.

For a recognized regression the service pins original Git blobs under `refs/localtuya-guard/<event>/<file-index>`, atomically replaces only the affected method with its exact fixed form, preserves ownership/mode, runs preflight and live check_config, reserves its one restart before dispatch, and verifies a new container start plus API readiness with unchanged expected package bytes. Failed pre-restart checks restore owned candidate bytes only; intervening edits are preserved. It reconciles an already-issued restart after interruption and never repeats it. A reserved restart that did not complete requires owner review. There is no key rotation, pairing/reset, .storage edit, or unrelated integration change.

When source is healthy, each currently-on pair gets a bounded small local dim (never a brightness increase), followed by restoration through its cloud twin. Both must agree within one HA brightness unit after each command. Off lamps or a level too low for a meaningful dim defer testing until both twins are on above three HA brightness units; an unavailable device or failed test requires review, not a guessed patch. Unexpected brightness/off changes cancel restoration to preserve user intent. A physical change exactly matching the original or requested test level cannot be distinguished from propagation. Interrupted tests do not blindly restore a level a user might have adopted; the service alerts for manual review. Service/HTTP failures can therefore leave the test level in place: check the notification/journal and adjust manually.

Jev `typesafe/jev-1.13` receives only recognized-source flags, defect count, repair flag and test-result enums through the typed System One endpoint. Existing Pi `.hermes/.env` credentials stay on the Pi; HA uses loopback. Jev has no patch/restart authority. Invalid, uncertain or unavailable results are recorded alongside deterministic results. Calls are bounded and metered, once per meaningful outcome; unchanged/off checkpoints cause no repeated calls or controls.

## Operations

Read status:

```sh
systemctl status localtuya-update-guard.service
journalctl -u localtuya-update-guard.service --since today
cat /home/arshad14/.local/state/localtuya-update-guard/checkpoint.json
python3 /opt/homeassistant/scripts/localtuya_update_guard.py --inspect
```

The checkpoint and per-event reports live under `/home/arshad14/.local/state/localtuya-update-guard/` (0600 records), outside the repo/frontend. Terminal results are `healthy`, `deferred`, or `needs_review`. HA persistent notifications use `localtuya_update_guard`; unchanged healthy results remain quiet. Failed deliveries retry until delivered. A failed command/readiness event does not loop on an unchanged fingerprint. Review and explicitly authorize a retry rather than deleting its checkpoint casually.

Disable with owner approval:

```sh
sudo systemctl disable --now localtuya-update-guard.service
```

Recovery bytes are Git objects, never .bak files. Read an event's `recovery` map and retrieve with `git cat-file blob <blob>`. Verify current candidate hash before restoring; run preflight/check_config and obtain approval before a manual restart.

The smoke harness supports `SMOKE_PI_HOST=__local__` for execution on the Pi; its existing Mac default is unchanged. Guard post-restart smoke sets `SMOKE_SKIP_LOCAL_INFERENCE=1` so it cannot load a local multi-GB model; the suite records the explicit skip. Manual default smoke behavior is unchanged. Guard smoke is bounded to 45 seconds and its result is journaled independently of the targeted light test. Full-suite success must not be inferred from a targeted pass.

## Verification

```sh
python3 -m unittest discover -s verification -p test_localtuya_guard.py
python3 verification/test_localtuya_payloads.py
bash verification/preflight.sh
```

Tests use temporary fixtures and fake HA/restart/model transports. Coverage includes both/one/neither defects, unknown methods/templates/partial syntax, same-version reinstall, concurrent edits and rollback preservation, gate failure, restart reservation/reconciliation, repeat suppression, propagation lag, unavailable/off devices, user intervention, restoration failure, interrupted tests and malformed/unavailable Jev. Real update recovery is simulated; no actual HACS upgrade was performed for acceptance. See the dated audit for deployment/live evidence.

Owner explicitly confirmed “Design approved” on 2026-09-30. The reviewed deployment and unattended repair/restart scope is approved; remaining work is blocked by Pi connectivity, not permission.
