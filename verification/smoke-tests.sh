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
ssh $PI "docker exec homeassistant python3 -c \"
import json
d = json.load(open('/config/.storage/core.config_entries'))
agents = [e['title'] for e in d['data']['entries'] if e['domain'] in ('ollama','google_generative_ai_conversation','openai_conversation')]
print('  registered agents:', agents)
expected = {'Local Chat','Local Control','Gemini','Claude'}
missing  = expected - set(agents)
print('  missing:', missing if missing else 'none')
import sys; sys.exit(1 if missing else 0)
\"" && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo
echo "=== 4. Proactive automations installed ==="
for a in proactive_front_door_left_open proactive_welcome_home proactive_nightly_lock_check; do
  check "$a present"  ssh $PI "docker exec homeassistant grep -q 'id: $a' /config/automations.yaml"
done

echo
echo "=== 5. End-to-end via HA REST API ==="
echo "  (Requires HA long-lived access token in env: HA_TOKEN)"
if [[ -n "${HA_TOKEN:-}" ]]; then
  for agent in conversation.local_chat conversation.local_control; do
    out=$(curl -s -X POST -H "Authorization: Bearer ${HA_TOKEN}" -H "Content-Type: application/json" \
      -d "{\"text\":\"Reply only PONG\",\"agent_id\":\"$agent\"}" \
      http://homeassistant.local:8123/api/conversation/process)
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
