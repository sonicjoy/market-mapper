#!/usr/bin/env bash
# Synthetic-fixture job: mint opticodds_fixtures + market_mapping rows for
# un-covered Kalshi series (ITF doubles + singles gaps) so they can be priced
# in-play off the Kalshi order book.  Runs as its own cron, independent of the
# mapping pipeline (run_pipeline.sh).  Exits non-zero on failure so
# cron_itf_synth.sh reports it.
#
# Schedule lives in infra/crontab (installed on deploy):
#   10-59/15 * * * * $HOME/mmmapper/infra/cron_itf_synth.sh
#
# What it runs on is data-driven: synthetic/series.toml. Add a [[series]] block
# there to onboard a new league/market — no code change. The gate skips anything
# ORIGINAL or GREG already maps, so it only fills the genuine no-fixture gap.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Serialize runs.  A slow Kalshi fetch must never overlap the next 15-min
# tick: two concurrent delete-then-append writes into market_mapping produce
# exact duplicate keys (BigQuery has no unique constraint), which then trip
# the mapping pipeline's post-MERGE uniqueness guard.  Own lock file — must
# not share pipeline.lock; the jobs are independent and must not starve each
# other.  Non-blocking; skip exits 0 so cron_itf_synth.sh does not Slack-alert.
LOCK_FILE="$REPO_DIR/logs/synthetic.lock"
mkdir -p "$REPO_DIR/logs"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — skip: previous synthetic-fixture run still active"
    exit 0
fi

# Load .env (GCP_PROJECT etc.) — cron has no user environment.  Same guarded
# KEY=VALUE parse as run_kalshi_raw.sh (final no-newline line preserved).
if [ -f .env ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$key=$value"
    done < .env
fi

PYTHON=".venv/bin/python"

echo ""
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — synthetic-fixture job start"
$PYTHON -m synthetic.run
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — synthetic-fixture job complete"
