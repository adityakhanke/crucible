#!/usr/bin/env bash
# CRUCIBLE — Nightly SCOUT script
# Add to cron: 0 2 * * * /path/to/crucible/scripts/scout.sh
#
# Discovers new papers, downloads, parses, and ingests claims.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/data/logs"

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"
source .venv/bin/activate

LOGFILE="$LOG_DIR/scout_$(date +%Y%m%d_%H%M%S).log"

echo "$(date) — SCOUT starting" >> "$LOGFILE"
python -m crucible scout 2>&1 >> "$LOGFILE"
echo "$(date) — SCOUT complete" >> "$LOGFILE"
