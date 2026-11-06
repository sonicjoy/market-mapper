#!/usr/bin/env bash
# Rebuild the Polymarket position_id <-> clob_token_id bridge from
# combos-rfq + Gamma and MERGE into
# raw_ingestion_us.polymarket_position_token_bridge.
#
# Own cron, independent of run_pipeline.sh — must not hold pipeline.lock.
# Coverage accumulates (MERGE keyed on position_id). fetch.polymarket on
# the mapping tick reads the last successful MERGE.
#
# Schedule lives in infra/crontab (installed on deploy):
#   8,23,38,53 * * * * $HOME/mmmapper/infra/cron_polymarket_bridge.sh
#
# Ad-hoc / backfill:
#   .venv/bin/python -m BigQuery.load_polymarket_position_bridge --cids-file legs.txt

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

LOCK_FILE="$REPO_DIR/logs/polymarket_bridge.lock"
mkdir -p "$REPO_DIR/logs"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — skip: previous polymarket bridge run still active"
    exit 0
fi

# Load .env (GCP_PROJECT etc.) — essential for cron, which has no
# user environment.  Parses KEY=VALUE only; won't execute arbitrary
# shell in .env.
if [ -f .env ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$key=$value"
    done < .env
fi

PYTHON=".venv/bin/python"

# --- Disk preflight ---
AVAIL_KB=$(df --output=avail -k . | tail -1 | tr -d ' ')
if [ "$AVAIL_KB" -lt 1048576 ]; then
    echo "FATAL: disk nearly full ($(( AVAIL_KB / 1024 ))MiB free < 1GiB) — run infra/disk_cleanup.sh" >&2
    exit 1
fi

echo ""
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Polymarket bridge start"
$PYTHON -m BigQuery.load_polymarket_position_bridge
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Polymarket bridge complete"
