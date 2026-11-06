#!/usr/bin/env bash
# Daily: scrape every Polymarket token's final resolution price (CLOB /markets) and
# upsert to raw_ingestion_us.polymarket_token_resolutions.  Independent of the
# bridge/combos.  Exits non-zero on failure so the wrapper reports.
#
# NOTE: this does a FULL oldest-first sweep of ~1M+ markets (a few minutes) to reach
# the recent/settled ones, hence daily not hourly.  To run more often + cheaply, pass
# --start-offset near the current market count so it only pages the tail, e.g.
#   $PYTHON -m BigQuery.load_polymarket_token_resolutions --start-offset 1300000
#
# Crontab entry:
#   30 4 * * * $HOME/mmmapper/infra/cron_polymarket_token_resolutions.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

if [ -f .env ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$key=$value"
    done < .env
fi

PYTHON=".venv/bin/python"

echo ""
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Polymarket token resolutions start"
$PYTHON -m BigQuery.load_polymarket_token_resolutions
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Polymarket token resolutions complete"
