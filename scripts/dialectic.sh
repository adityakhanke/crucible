#!/usr/bin/env bash
# CRUCIBLE — Periodic DIALECTIC cycle script
# Add to cron: 0 6 */3 * * /path/to/crucible/scripts/dialectic.sh
#
# Runs a full 5-phase dialectical analysis cycle.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/data/logs"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"
source .venv/bin/activate

LOGFILE="$LOG_DIR/dialectic_$(date +%Y%m%d_%H%M%S).log"

echo "$(date) — DIALECTIC starting" >> "$LOGFILE"
python -m crucible dialectic 2>&1 >> "$LOGFILE"
echo "$(date) — DIALECTIC complete" >> "$LOGFILE"
