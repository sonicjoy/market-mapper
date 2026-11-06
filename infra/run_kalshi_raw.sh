#!/usr/bin/env bash
# 6-hourly raw-stash: fetch every Kalshi Sports market and load
# the raw records to raw_ingestion_us.kalshi_raw.  Runs as its own
# cron, independent of the mapping pipeline (run_pipeline.sh).
# Exits non-zero on any failure so cron_kalshi_raw.sh reports it.
#
# Schedule lives in infra/crontab (installed on deploy):
#   7 */6 * * * $HOME/mmmapper/infra/cron_kalshi_raw.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Load .env (GCP_PROJECT etc.) — essential for cron, which has no
# user environment.  Parses KEY=VALUE only; won't execute arbitrary
# shell in .env.
# The `|| [ -n "$key" ]` guard processes a final line with no trailing
# newline; without it, `read` returns false at EOF and the last entry
# (e.g. GCP_PROJECT) is silently dropped.
if [ -f .env ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$key=$value"
    done < .env
fi

PYTHON=".venv/bin/python"

# --- Disk preflight ---
# Fail fast with an actionable message instead of an OSError mid-fetch,
# so the Slack alert tail shows the cause rather than progress noise.
AVAIL_KB=$(df --output=avail -k . | tail -1 | tr -d ' ')
if [ "$AVAIL_KB" -lt 1048576 ]; then
    echo "FATAL: disk nearly full ($(( AVAIL_KB / 1024 ))MiB free < 1GiB) — run infra/disk_cleanup.sh" >&2
    exit 1
fi

STAMP="$(date -u '+%Y-%m-%d/%H_%M')"
OUT_DIR="data_raw/$STAMP"
JSONL="$OUT_DIR/kalshi_markets_raw.jsonl"

echo ""
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Raw-stash start"

# --- Fetch every Sports series, raw ---
$PYTHON -m fetch.kalshi_all --out-dir "$OUT_DIR"

# --- Load to BigQuery ---
$PYTHON -m BigQuery.load_kalshi_raw "$JSONL"

# --- Delete JSONL after confirmed load ---
# The BQ table is the canonical store; keeping local copies wastes
# disk and gives a false impression of recoverability.  Empty dated
# parent dirs are removed quietly; failures don't matter.
rm "$JSONL"
rmdir "$OUT_DIR" 2>/dev/null || true
rmdir "$(dirname "$OUT_DIR")" 2>/dev/null || true

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Raw-stash complete"
