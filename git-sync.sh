#!/bin/bash
# HA Config Git Sync Script
# Runs from cron — commits and pushes any HA config changes to GitHub
# Installed at /opt/homeassistant/git-sync.sh

REPO_DIR="/opt/homeassistant"
LOG_FILE="/var/log/ha-git-sync.log"
BRANCH="main"

cd "$REPO_DIR" || exit 1

# Only proceed if the repo is clean enough to operate
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] ERROR: $REPO_DIR is not a git repo" >> "$LOG_FILE"
    exit 1
fi

# Check if there are any tracked changes
if [ -z "$(git status --porcelain)" ]; then
    exit 0  # nothing to do — stay silent
fi

# Stage all changes (respecting .gitignore)
git add -A

# Commit with timestamp
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S %Z")
git commit -m "Auto-sync: $TIMESTAMP" --no-verify >/dev/null 2>&1

# Push
if git push origin "$BRANCH" >>"$LOG_FILE" 2>&1; then
    echo "[$TIMESTAMP] Pushed to origin/$BRANCH" >> "$LOG_FILE"
else
    echo "[$TIMESTAMP] ERROR: push failed" >> "$LOG_FILE"
fi
