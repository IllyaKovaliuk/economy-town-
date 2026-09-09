#!/bin/bash
# Advances the town by exactly one time-of-day phase. Meant to be triggered by
# cron at real times of day (morning/afternoon/evening) so the town's day
# actually runs alongside the real one instead of firing all at once.
#
# cron has no shell profile / venv / PATH by default, so this script sets
# everything up explicitly. All output goes to logs/cron.log for later review
# (cron runs headless — there's no terminal to see it in at the time).

cd "$(dirname "$0")" || exit 1
mkdir -p logs
source .venv/bin/activate
{
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="
    python3 main.py --rounds 1
    echo
} >> logs/cron.log 2>&1
