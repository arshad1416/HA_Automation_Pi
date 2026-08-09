#!/usr/bin/env bash
# Exercises the alert block of git-sync.sh against a real git repo with a real
# backlog. Stubs python3 so nothing is sent to Telegram.
set -u
# git-sync.sh lives at the repo root; this test lives in verification/.
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$REPO/git-sync.sh"
[ -f "$SCRIPT" ] || { echo "cannot find $SCRIPT"; exit 1; }
# Scratch dir MUST live outside the repo — git-sync.sh runs `git add -A`, so
# anything left inside would be committed to the config repo.
T="$(mktemp -d "${TMPDIR:-/tmp}/gitsync-alert-test.XXXXXX")"
trap 'rm -rf "$T"' EXIT

# --- build the block-under-test from the real script ------------------------
python3 - "$SCRIPT" "$T/block.sh" "$T/alerted" <<'PYEOF'
import sys
src, dst, flag = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(src).read()
start = text.index("# --- 0. Alert when earlier runs left commits stranded")
end = text.index("TIMESTAMP=$(date")
block = text[start:end]
# Redirect the production flag path at the test's own flag (portable: no sed -i,
# which differs between BSD/macOS and GNU/Linux).
assert "/var/tmp/ha-git-sync.alerted" in block, "flag path moved — update this test"
block = block.replace("/var/tmp/ha-git-sync.alerted", flag)
# python3 in the block becomes a stub that records the message instead of sending.
open(dst, "w").write(
    '#!/usr/bin/env bash\n'
    'python3() { cat >> "$SENT"; printf "\\n---\\n" >> "$SENT"; }\n'
    'BRANCH=main\n'
    + block
)
PYEOF

# --- a real repo with a real origin so git rev-list is genuine --------------
git init -q --bare "$T/origin.git"
git clone -q "$T/origin.git" "$T/repo"
cd "$T/repo"
git config user.email t@t; git config user.name t
echo a > f; git add f; git commit -qm base; git push -q origin main 2>/dev/null || git push -q origin master
git branch -M main 2>/dev/null; git push -q -u origin main 2>/dev/null

export SENT="$T/sent.txt"; : > "$SENT"
export LOG_FILE="$T/log.txt"; : > "$LOG_FILE"

run() {  # run the block inside the test repo
  ( cd "$T/repo" && LOG_FILE="$LOG_FILE" SENT="$SENT" \
      bash -c "source '$T/block.sh'" )
}

pass=0; fail=0
check() { # check <desc> <expected> <actual>
  if [ "$2" = "$3" ]; then echo "  ok   $1"; pass=$((pass+1));
  else echo "  FAIL $1 (expected '$2', got '$3')"; fail=$((fail+1)); fi
}

commits() { for i in $(seq 1 "$1"); do echo "x$i" >> f; git add f; git commit -qm "c$i"; done; }


echo "== 1. backlog 0 -> silent =="
run; check "no message"      "0" "$(grep -c -- --- "$SENT")"
check "no flag"              "absent" "$([ -f "$T/alerted" ] && echo present || echo absent)"

echo "== 2. backlog 3 (below threshold) -> still silent =="
commits 3; run
check "no message"           "0" "$(grep -c -- --- "$SENT")"

echo "== 3. backlog 5 (over threshold) -> ONE alert + flag =="
commits 2; run
check "one message"          "1" "$(grep -c -- --- "$SENT")"
check "flag created"         "present" "$([ -f "$T/alerted" ] && echo present || echo absent)"
check "message names count"  "1" "$(grep -c '5 commits are stranded' "$SENT")"
check "logged"               "1" "$(grep -c 'ALERT sent: 5 commits unpushed' "$LOG_FILE")"

echo "== 4. still failing, backlog grows -> NO re-alert (the spam guard) =="
commits 4; run; run
check "still one message"    "1" "$(grep -c -- --- "$SENT")"

echo "== 5. push succeeds -> recovery message, flag cleared =="
git push -q origin main; run
check "recovery message"     "1" "$(grep -c 'recovered' "$SENT")"
check "flag cleared"         "absent" "$([ -f "$T/alerted" ] && echo present || echo absent)"
check "logged clear"         "1" "$(grep -c 'ALERT cleared' "$LOG_FILE")"

echo "== 6. steady state after recovery -> silent again =="
before=$(grep -c -- --- "$SENT"); run
check "no new message"       "$before" "$(grep -c -- --- "$SENT")"

echo "== 7. missing origin ref -> treated as 0, no crash/alert =="
before=$(grep -c -- --- "$SENT")
( cd "$T/repo" && git update-ref -d refs/remotes/origin/main )
run; rc=$?
check "exit 0 (no crash)"    "0" "$rc"
check "no message"           "$before" "$(grep -c -- --- "$SENT")"

echo
echo "passed=$pass failed=$fail"
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
