#!/bin/bash
# Big0Time Project Sync Cron Script
# Run this to sync projects from GitHub directory to BIG0TIME index

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Run the sync script
python3 sync_projects.py

# If there were changes, commit and push
if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git commit -m "Auto-sync projects: $(date '+%Y-%m-%d %H:%M')"
    git push
fi
