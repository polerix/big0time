#!/bin/bash
# Big0Time Project Sync Cron Script
# Run this to sync projects from GitHub directory to big0time index

LOCKFILE="/tmp/big0time_sync.lock"

# Simple lock mechanism
if [ -e "$LOCKFILE" ]; then
    # Check if process is still running
    if ps -p $(cat "$LOCKFILE") > /dev/null; then
        exit 1
    fi
fi
echo $$ > "$LOCKFILE"

# Ensure lock is removed on exit
trap 'rm -f "$LOCKFILE"; exit' INT TERM EXIT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Run the sync script, logging output to a temporary file
SYNC_LOG="/tmp/big0time_sync.log"
python3 sync_projects_portable.py > "$SYNC_LOG" 2>&1

# If there were changes, commit and push
if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git commit -m "Auto-sync projects: $(date '+%Y-%m-%d %H:%M')" >> "$SYNC_LOG" 2>&1
    git push >> "$SYNC_LOG" 2>&1
fi

# Only report if there's an error (last command failed)
if [ $? -ne 0 ]; then
    cat "$SYNC_LOG"
fi
