#!/bin/bash
# HA Config Git Sync Script
# Runs from cron — commits and pushes any HA config changes to GitHub.
# Installed at /opt/homeassistant/git-sync.sh
#
# MULTI-WRITER SAFE: the curated Mac repo (~/Developer/HA_Automation_Pi) also
# pushes to origin/main, so this script always incorporates remote commits first
# via `git pull --rebase --autostash` before committing/pushing local changes.
# Conflicts preserve the pre-pull files and pause sync for owner reconciliation.

REPO_DIR="/opt/homeassistant"
LOG_FILE="/var/log/ha-git-sync.log"
BRANCH="main"

cd "$REPO_DIR" || exit 1

# Only proceed if this is a git working tree
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] ERROR: $REPO_DIR is not a git repo" >> "$LOG_FILE"
    exit 1
fi

# --- 0. Alert when earlier runs left commits stranded ------------------------
# Every failure path in this script only writes to $LOG_FILE, and nothing reads
# that file. On 2026-08-07 a push blocked by GitHub secret scanning went unnoticed
# for ~33h and 134 commits, because from cron's point of view the job kept running
# fine. Checking the BACKLOG rather than hooking each failure branch catches every
# stranding cause at once — including a persistently failing pull --rebase, which
# exits below before the push is ever attempted.
ALERT_AFTER=4                               # 15-min cycles, so roughly one hour
ALERT_FLAG="/var/tmp/ha-git-sync.alerted"   # presence = "already told them"

notify() {
    # Message arrives on stdin so it is never interpolated into python source.
    printf '%s' "$1" | python3 -c \
        "import sys; sys.path.insert(0,'/home/arshad14/.hermes/scripts'); from tg_notify import send_telegram; sys.exit(0 if send_telegram(sys.stdin.read()) else 1)" \
        >>"$LOG_FILE" 2>&1
}

# Non-numeric or empty (e.g. origin/$BRANCH ref missing) is treated as no backlog.
BACKLOG=$(git rev-list --count "origin/$BRANCH..HEAD" 2>/dev/null)
case "$BACKLOG" in ''|*[!0-9]*) BACKLOG=0 ;; esac

if [ "$BACKLOG" -gt "$ALERT_AFTER" ] && [ ! -f "$ALERT_FLAG" ]; then
    if notify "HA git-sync: GitHub backup is FAILING.

$BACKLOG commits are stranded on the Pi, so the .storage/ disaster-recovery
chain is stale and getting staler.

Diagnose: ssh pi-lan \"tail -40 $LOG_FILE\""; then
        touch "$ALERT_FLAG"
        echo "[$(date '+%F %T')] ALERT sent: $BACKLOG commits unpushed" >> "$LOG_FILE"
    else
        echo "[$(date '+%F %T')] WARN: backlog alert delivery failed; will retry" >> "$LOG_FILE"
    fi
elif [ "$BACKLOG" -eq 0 ] && [ -f "$ALERT_FLAG" ]; then
    # An alert that never says "resolved" trains you to ignore it.
    if notify "HA git-sync: recovered. Backlog drained; GitHub backup is current again."; then
        rm -f "$ALERT_FLAG"
        echo "[$(date '+%F %T')] ALERT cleared: backlog drained" >> "$LOG_FILE"
    else
        echo "[$(date '+%F %T')] WARN: recovery alert delivery failed; will retry" >> "$LOG_FILE"
    fi
fi

TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S %Z")

# Keep a pinned pre-pull tree: Git autostash recovery must not replace curated
# working files with origin/main. The marker stops subsequent cron runs until
# the owner reconciles both writers. Alert retries happen at most once per run.
RECOVERY_REF="refs/ha-git-sync/pre-pull"
CONFLICT_FLAG=$(git rev-parse --git-path ha-git-sync.conflict) || exit 1
CONFLICT_ALERT="$CONFLICT_FLAG.notified"
conflict_alert() {
    if [ ! -f "$CONFLICT_ALERT" ]; then
        if notify "HA git-sync: conflict requires owner review. Synchronization is paused; inspect the working tree, $RECOVERY_REF and $CONFLICT_FLAG before resuming."; then
            touch "$CONFLICT_ALERT"
        else
            echo "[$TIMESTAMP] WARN: conflict alert delivery failed; will retry" >> "$LOG_FILE"
        fi
    fi
}
if [ -f "$CONFLICT_FLAG" ] || [ -n "$(git diff --name-only --diff-filter=U)" ]; then
    touch "$CONFLICT_FLAG"
    conflict_alert
    echo "[$TIMESTAMP] ERROR: unresolved conflict; sync paused for owner review" >> "$LOG_FILE"
    exit 1
fi

# --- 0b. Repair ownership before git touches the tree -------------------------
# HACS runs inside the privileged HA container as root, so an integration update
# writes root:root files into custom_components/. git then cannot unlink them as
# $(id -un) and every `pull --rebase` dies with "unable to unlink old ... /
# Permission denied". On 2026-08-22 a govee update did exactly this and wedged
# the sync completely. Re-chowning what we own is cheap and idempotent; the
# container is root and unaffected by the change.
FOREIGN=$(find . -path ./.git -prune -o ! -user "$(id -un)" -print 2>/dev/null | head -1)
if [ -n "$FOREIGN" ]; then
    if sudo -n chown -R "$(id -un):$(id -gn)" "$REPO_DIR" >>"$LOG_FILE" 2>&1; then
        echo "[$TIMESTAMP] Repaired foreign file ownership (e.g. $FOREIGN)" >> "$LOG_FILE"
    else
        echo "[$TIMESTAMP] WARN: foreign-owned files present and chown failed: $FOREIGN" >> "$LOG_FILE"
    fi
fi

# --- 1. Incorporate remote commits (other writers may have pushed to main) ---
# --autostash temporarily stashes the ever-changing local telemetry, rebases any
# local commits onto origin/$BRANCH, then restores the stash.
LOCAL_SNAPSHOT=$(git stash create) || exit 1
if [ -n "$LOCAL_SNAPSHOT" ]; then
    git update-ref "$RECOVERY_REF" "$LOCAL_SNAPSHOT" || exit 1
fi
PULL_OK=1
if ! git pull --rebase --autostash origin "$BRANCH" >>"$LOG_FILE" 2>&1; then
    git rebase --abort >>"$LOG_FILE" 2>&1 || true
    PULL_OK=0
fi
if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
    printf '%s\n' "$RECOVERY_REF" > "$CONFLICT_FLAG" || exit 1
    if [ -n "$LOCAL_SNAPSHOT" ]; then
        if git restore --source="$LOCAL_SNAPSHOT^2" --staged -- . >>"$LOG_FILE" 2>&1 &&
           git restore --source="$LOCAL_SNAPSHOT" --worktree -- . >>"$LOG_FILE" 2>&1; then
            echo "[$TIMESTAMP] Preserved pre-pull index and working files; recovery pinned at $RECOVERY_REF" >> "$LOG_FILE"
        else
            echo "[$TIMESTAMP] ERROR: restore incomplete; recovery pinned at $RECOVERY_REF" >> "$LOG_FILE"
        fi
    fi
    conflict_alert
    echo "[$TIMESTAMP] ERROR: autostash conflict; sync paused for owner review" >> "$LOG_FILE"
    exit 1
fi
if [ "$PULL_OK" -eq 0 ]; then
    echo "[$TIMESTAMP] ERROR: pull --rebase failed; will retry next run" >> "$LOG_FILE"
    # A failing pull exits BEFORE anything is committed, so the backlog stays 0
    # and the step-0 guard above can never notice. That is how the 2026-08-22
    # permission wedge stayed invisible: sync was dead, backlog said "fine".
    # Track consecutive pull failures separately and alert on persistence.
    PF_FLAG="/var/tmp/ha-git-sync.pullfail"
    PF=$(( $(cat "$PF_FLAG" 2>/dev/null || echo 0) + 1 ))
    echo "$PF" > "$PF_FLAG"
    PF_ALERT="$PF_FLAG.notified"
    if [ "$PF" -ge "$ALERT_AFTER" ] && [ ! -f "$PF_ALERT" ]; then
        if notify "HA git-sync: pull --rebase is FAILING.

$PF consecutive runs could not incorporate origin/$BRANCH, so nothing is being
backed up and Mac-side pushes are not reaching the Pi. Backlog stays 0, so the
stranded-commits alert cannot see this.

Diagnose: ssh pi-lan \"tail -40 $LOG_FILE\""; then
            touch "$PF_ALERT"
        else
            echo "[$TIMESTAMP] WARN: pull-failure alert delivery failed; will retry" >> "$LOG_FILE"
        fi
    fi
    exit 1
fi
rm -f /var/tmp/ha-git-sync.pullfail /var/tmp/ha-git-sync.pullfail.notified
if [ -n "$LOCAL_SNAPSHOT" ]; then
    git update-ref -d "$RECOVERY_REF" "$LOCAL_SNAPSHOT" || exit 1
fi

# --- 2. Commit new edits, independently of retrying unpublished commits. ---
if [ -n "$(git status --porcelain)" ]; then
    # --- 3. Stage + commit local changes (respecting .gitignore) ---
    if ! git add -A >>"$LOG_FILE" 2>&1 ||
       ! git commit -m "Auto-sync: $TIMESTAMP" --no-verify >>"$LOG_FILE" 2>&1; then
        echo "[$TIMESTAMP] ERROR: stage/commit failed" >> "$LOG_FILE"
        exit 1
    fi
fi
UNPUBLISHED=$(git rev-list --count "origin/$BRANCH..HEAD") || exit 1
if [ "$UNPUBLISHED" -eq 0 ]; then
    exit 0
fi

# --- 4. Push ---
if git push origin "$BRANCH" >>"$LOG_FILE" 2>&1; then
    echo "[$TIMESTAMP] Pushed to origin/$BRANCH" >> "$LOG_FILE"
else
    echo "[$TIMESTAMP] ERROR: push failed (will retry next run)" >> "$LOG_FILE"
    exit 1
fi
