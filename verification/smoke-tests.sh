#!/usr/bin/env bash
# Phase 8 verification — run after HA integrations are added and automations installed.
# Read-only checks against the Pi. Run from the Mac:  bash verification/smoke-tests.sh
set -uo pipefail

PI=pi-lan
PASS=0; FAIL=0
check() { local name="$1"; shift; if "$@" >/dev/null 2>&1; then echo "  ✓ $name"; PASS=$((PASS+1)); else echo "  ✗ $name"; FAIL=$((FAIL+1)); fi; }

echo "=== 1. Pi prerequisites ==="
check "Ollama service active"          ssh $PI "systemctl is-active ollama | grep -q active"
check "Ollama 0.21.2"                  ssh $PI "ollama --version | grep -q 0.21.2"
check "Ollama listening *:11434"       ssh $PI "ss -tln | grep -q ':11434 '"
check "gemma3-tools:4b-ft pulled"      ssh $PI "ollama list | grep -q 'orieg/gemma3-tools:4b-ft'"
check "qwen2.5:7b contingency pulled"  ssh $PI "ollama list | grep -q 'qwen2.5:7b'"
check "tools capability declared"      ssh $PI "ollama show orieg/gemma3-tools:4b-ft | grep -A4 Capabilities | grep -qw tools"

echo
echo "=== 2. Local brain inference (warm latency) ==="
ssh $PI 'curl -s http://localhost:11434/api/chat -d "{\"model\":\"orieg/gemma3-tools:4b-ft\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply only PONG\"}],\"stream\":false}"' \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); c=r["message"]["content"].strip(); d=r.get("total_duration",0)/1e9; print(f"  response={c!r}  duration={d:.1f}s"); sys.exit(0 if "PONG" in c else 1)' \
  && echo "  ✓ PONG via /api/chat" && PASS=$((PASS+1)) \
  || { echo "  ✗ PONG via /api/chat"; FAIL=$((FAIL+1)); }

echo
echo "=== 3. HA conversation agents present ==="
# 2026-08-09: assert on `domain` (stable) instead of entry titles. The old expected set
# {Local Chat,Local Control,Gemini,Claude} matched nothing — live titles are now
# 'http://localhost:11434' and 'Google Generative AI'. Titles + entities are printed for drift.
ssh $PI "docker exec homeassistant python3 -c \"
import json, sys
CONV = ('ollama','google_generative_ai_conversation','openai_conversation','open_router','anthropic')
entries  = [e for e in json.load(open('/config/.storage/core.config_entries'))['data']['entries'] if e['domain'] in CONV]
entities = [e['entity_id'] for e in json.load(open('/config/.storage/core.entity_registry'))['data']['entities'] if e['entity_id'].startswith('conversation.')]
print('  config entries:', sorted((e['domain'], e['title']) for e in entries))
print('  conversation entities:', sorted(entities))
missing = {'ollama','google_generative_ai_conversation'} - {e['domain'] for e in entries}
print('  missing domains:', missing or 'none')
sys.exit(1 if missing else 0)
\"" && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo
echo "=== 4. Proactive automations installed ==="
# 2026-08-07: /config/automations.yaml retired (stub + []). Automations load from
# automations/ via !include_dir_merge_list. With HA_TOKEN set we ask the state machine instead.
for a in proactive_front_door_left_open proactive_welcome_home proactive_nightly_lock_check; do
  if [[ -n "${HA_TOKEN:-}" ]]; then
    check "automation.$a live" ssh $PI "curl -sf -o /dev/null -H 'Authorization: Bearer ${HA_TOKEN}' http://localhost:8123/api/states/automation.$a"
  else
    check "$a in automations/" ssh $PI "docker exec homeassistant grep -rqE '^ *id: $a\$' /config/automations/"
  fi
done
[[ -n "${HA_TOKEN:-}" ]] || echo "  (file-level check only — set HA_TOKEN to query the HA state machine instead)"

echo
echo "=== 5. End-to-end via HA REST API ==="
echo "  (Requires HA long-lived access token in env: HA_TOKEN)"
# 2026-08-09: agent list discovered from the entity registry instead of hardcoded.
# conversation.local_chat / conversation.local_control were hardcoded here and no longer exist
# (the Ollama config entry registers no conversation entities). Routed via ssh like sections 1-4
# rather than the Mac's only mDNS dependency.
if [[ -n "${HA_TOKEN:-}" ]]; then
  # One agent per config entry — proves each integration's pipeline without billing every
  # OpenRouter sub-agent on each run.
  agents=$(ssh $PI "docker exec homeassistant python3 -c \"
import json
ents = [e for e in json.load(open('/config/.storage/core.entity_registry'))['data']['entities'] if e['entity_id'].startswith('conversation.') and not e.get('disabled_by')]
per_entry = {}
for e in sorted(ents, key=lambda x: x['entity_id']):
    per_entry.setdefault(e['config_entry_id'], e['entity_id'])
print(' '.join(per_entry.values()))
\"")
  if [[ -z "$agents" ]]; then echo "  ✗ no conversation agents found in entity registry"; FAIL=$((FAIL+1)); fi
  echo "  agents under test (1 per config entry, some cloud-billed): ${agents:-none}"
  for agent in $agents; do
    [[ $agent == conversation.* ]] || continue
    out=$(ssh $PI "curl -s -X POST -H 'Authorization: Bearer ${HA_TOKEN}' -H 'Content-Type: application/json' -d '{\"text\":\"Reply only PONG\",\"agent_id\":\"$agent\"}' http://localhost:8123/api/conversation/process")
    echo "$out" | grep -q PONG && echo "  ✓ $agent → PONG" && PASS=$((PASS+1)) || { echo "  ✗ $agent (out: $out)"; FAIL=$((FAIL+1)); }
  done
else
  echo "  (skipped — set HA_TOKEN env var to run)"
fi

echo
echo "=== Summary ==="
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
[[ $FAIL -eq 0 ]] || exit 1
