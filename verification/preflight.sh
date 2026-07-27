#!/usr/bin/env bash
# Pre-deploy syntax gate for this repo's curated config and daemons.
# Catches Python and YAML syntax errors BEFORE files are copied to the Pi.
# This is NOT full validation — Home Assistant semantics are only checked by
# check_config inside the homeassistant container on the Pi (AGENTS.md, "Change workflow").
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 1

fail=0

echo "== Python syntax (root daemons + scripts/) =="
while IFS= read -r -d '' f; do
  if ! python3 -m py_compile "$f"; then
    echo "FAIL: $f"
    fail=1
  fi
done < <(find . -maxdepth 1 -name '*.py' -print0; find scripts -maxdepth 1 -name '*.py' -print0 2>/dev/null)
echo "python: done"

echo "== YAML syntax (curated config) =="
# Prefer any interpreter that has PyYAML: env override, plain python3 (the Pi),
# then the Mac's hq_venv (see ShiftLogic_HQ CLAUDE.md).
yaml_py=""
for cand in "${PREFLIGHT_PYTHON:-}" python3 "$HOME/Documents/ShiftLogic_HQ/hq_venv/bin/python3"; do
  [ -n "$cand" ] || continue
  if "$cand" -c 'import yaml' 2>/dev/null; then yaml_py="$cand"; break; fi
done
if [ -n "$yaml_py" ]; then
  if ! "$yaml_py" - <<'PYEOF'
import glob, sys, yaml

class HALoader(yaml.SafeLoader):
    """Accepts HA/ESPHome local tags (!include, !secret, !lambda, ...) without resolving them."""

HALoader.add_multi_constructor('!', lambda loader, suffix, node: None)

files = ['configuration.yaml', 'scenes.yaml', 'scripts.yaml', 'automations.yaml']
for pattern in ('automations/*.yaml', 'dashboards/*.yaml', 'esphome/*.yaml'):
    files += sorted(glob.glob(pattern))

checked = bad = 0
for path in files:
    try:
        with open(path) as fh:
            list(yaml.load_all(fh, Loader=HALoader))
        checked += 1
    except FileNotFoundError:
        continue
    except yaml.YAMLError as err:
        print(f'FAIL: {path}: {err}')
        checked += 1
        bad += 1
print(f'yaml: {checked} files checked, {bad} failed')
sys.exit(1 if bad else 0)
PYEOF
  then
    fail=1
  fi
else
  echo "SKIP: PyYAML not installed for python3 — YAML not parsed (pip install pyyaml)"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "preflight OK — full validation still requires check_config on the Pi before restart"
else
  echo "preflight FAILED — fix the errors above before deploying"
fi
exit "$fail"
