#!/bin/bash
# HA Config Git Sync Script
# Runs from cron — commits and pushes any HA config changes to GitHub.
# Installed at /opt/homeassistant/git-sync.sh
#
# MULTI-WRITER SAFE: the curated Mac repo (~/Developer/HA_Automation_Pi) also
# pushes to origin/main, so this script always incorporates remote commits first
# via `git pull --rebase --autostash` before committing/pushing local changes.
# Conflict guards bail out cleanly (never leaving the repo mid-rebase or pushing
# conflict markers); the next 15-min cycle retries.

REPO_DIR="/opt/homeassistant"
LOG_FILE="/var/log/ha-git-sync.log"
BRANCH="main"

cd "$REPO_DIR" || exit 1

# Only proceed if this is a git working tree
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] ERROR: $REPO_DIR is not a git repo" >> "$LOG_FILE"
    exit 1
fi

TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S %Z")

# --- 1. Incorporate remote commits (other writers may have pushed to main) ---
# --autostash temporarily stashes the ever-changing local telemetry, rebases any
# local commits onto origin/$BRANCH, then restores the stash.
if ! git pull --rebase --autostash origin "$BRANCH" >>"$LOG_FILE" 2>&1; then
    git rebase --abort >>"$LOG_FILE" 2>&1 || true
    echo "[$TIMESTAMP] ERROR: pull --rebase failed; will retry next run" >> "$LOG_FILE"
    exit 1
fi

# Belt-and-suspenders: if the autostash pop left unmerged paths, reset clean and
# bail rather than committing/pushing a broken tree. (Local telemetry regenerates.)
if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
    git reset --hard "origin/$BRANCH" >>"$LOG_FILE" 2>&1
    echo "[$TIMESTAMP] ERROR: autostash conflict; reset to origin/$BRANCH, retry next run" >> "$LOG_FILE"
    exit 1
fi

# --- 2. Nothing local to back up? We're fully synced — done. ---
if [ -z "$(git status --porcelain)" ]; then
    exit 0
fi

# --- 3. Stage + commit local changes (respecting .gitignore) ---
git add -A
if ! git commit -m "Auto-sync: $TIMESTAMP" --no-verify >>"$LOG_FILE" 2>&1; then
    echo "[$TIMESTAMP] ERROR: commit failed" >> "$LOG_FILE"
    exit 1
fi

# --- 4. Push ---
if git push origin "$BRANCH" >>"$LOG_FILE" 2>&1; then
    echo "[$TIMESTAMP] Pushed to origin/$BRANCH" >> "$LOG_FILE"
else
    echo "[$TIMESTAMP] ERROR: push failed (will retry next run)" >> "$LOG_FILE"
fi
