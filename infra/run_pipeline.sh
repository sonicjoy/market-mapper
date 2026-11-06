#!/usr/bin/env bash
# Mapping pipeline (every 15 min): fetch from exchanges, write mappings,
# load to BigQuery.  Called by cron.  Exits non-zero on any failure so
# cron reports it.
#
# Schedule lives in infra/crontab (installed on deploy); cron invokes the
# cron_pipeline.sh wrapper, which runs this script and alerts on failure:
#   */15 * * * * $HOME/mmmapper/infra/cron_pipeline.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Serialize runs.  At a 15-min cron cadence a tick must never queue
# behind a slower one (that would pile up unboundedly), so by default we
# grab the lock non-blocking and bow out cleanly when it's held; exiting
# 0 keeps a skip from looking like a failure to cron_pipeline.sh (which
# would otherwise Slack-alert on every skipped tick).  A deploy sets
# PIPELINE_LOCK_WAIT (seconds) to wait for the active run instead of
# skipping, so freshly deployed config still goes live promptly.
LOCK_WAIT="${PIPELINE_LOCK_WAIT:-0}"
LOCK_FILE="$REPO_DIR/logs/pipeline.lock"
mkdir -p "$REPO_DIR/logs"
exec 200>"$LOCK_FILE"
if [ "$LOCK_WAIT" -gt 0 ]; then
    if ! flock -w "$LOCK_WAIT" 200; then
        echo "FATAL: could not acquire pipeline lock within ${LOCK_WAIT}s" >&2
        exit 1
    fi
else
    if ! flock -n 200; then
        echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — skip: previous pipeline run still active"
        exit 0
    fi
fi

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

# Keep stdout in step with stderr in the log.  Redirected stdout is
# block-buffered, so a traceback (stderr, line-buffered) lands ahead of
# the prints that preceded it and the failure reads out of order.
export PYTHONUNBUFFERED=1

# --- Disk preflight ---
# Fail fast with an actionable message instead of an OSError mid-fetch,
# so the Slack alert tail shows the cause rather than progress noise.
AVAIL_KB=$(df --output=avail -k . | tail -1 | tr -d ' ')
if [ "$AVAIL_KB" -lt 1048576 ]; then
    echo "FATAL: disk nearly full ($(( AVAIL_KB / 1024 ))MiB free < 1GiB) — run infra/disk_cleanup.sh" >&2
    exit 1
fi

echo ""
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Pipeline start"
PIPELINE_T0=$(date +%s)

# Grep-friendly step timers for prod wall-time diagnosis:
#   STEP name=<step> sec=<integer>
_step_begin() { _STEP_T0=$(date +%s); }
_step_end() {
    local name="$1"
    local now
    now=$(date +%s)
    echo "STEP name=${name} sec=$((now - _STEP_T0))"
}

# Polymarket position bridge is NOT in this tick. The combos-rfq catalog
# page is ~6 min and held pipeline.lock, so mapping skipped every other
# :15. fetch.polymarket reads whatever is already in
# raw_ingestion_us.polymarket_position_token_bridge (MERGE is keyed on
# position_id; new combo legs appear on the next independent bridge cron).
# Schedule: infra/cron_polymarket_bridge.sh (own lock).

# --- Fetch ---
# Capture output to extract the timestamped directory path.
# Temporarily disable set -e so we always echo the output (including
# error messages) before exiting.  Without this, a fetch failure causes
# set -e to kill the script before the echo, and the error is lost.
set +e
# League list drives which Optic schedules are fetched (fetch.polymarket is
# league-agnostic — it always pulls the full position↔token bridge).  Map uses
# the same FETCH_LEAGUES list. A poly-mappable league only produces rows
# if its Optic fixtures are fetched here.
#
# DERIVED from the activated tip when MAPPING_SOT=bq (M5), else
# mappers.run.LEAGUES. A console-onboarded known-profile league is
# fetched on the next tick with no mapper deploy. Tip rows with
# fixture_source=bq|synthetic stay off this API fetch.
FETCH_LEAGUES=$($PYTHON -c '
from mappers.run import api_fetch_league_keys
print(" ".join(api_fetch_league_keys()))')
if [ -z "$FETCH_LEAGUES" ]; then
    echo "FATAL: could not derive the league list from tip / LEAGUES" >&2
    exit 1
fi
echo "Fetching leagues: $FETCH_LEAGUES"
_step_begin
FETCH_OUTPUT=$($PYTHON -m fetch --league $FETCH_LEAGUES --out-dir data 2>&1)
FETCH_EXIT=$?
_step_end fetch_total
set -e
# Full fetch output is thousands of per-fixture lines; echoing it into
# pipeline.log costs ~30–45s on the locked path. Keep summaries and alerts.
printf '%s\n' "$FETCH_OUTPUT" | grep -vE \
    '^  \[[0-9]+/[0-9]+\] |^  fetching with |^  clob page |^  px_get |^  markets batch ' \
    || true
if [ "$FETCH_EXIT" -ne 0 ]; then
    echo "FATAL: fetch exited with code $FETCH_EXIT" >&2
    exit "$FETCH_EXIT"
fi

OUTPUT=$(echo "$FETCH_OUTPUT" | grep '^Output: ' | cut -d' ' -f2)

if [ -z "$OUTPUT" ]; then
    echo "FATAL: fetch did not print output directory" >&2
    exit 1
fi

# --- Polymarket US gateway market harvest (Path 2 input; typed fields only) ---
_step_begin
$PYTHON -m fetch.polymarket_usa --out-dir "$OUTPUT" \
    || echo "WARN: polymarket_usa harvest failed (non-fatal) — map skips US Path 2"
_step_end poly_usa_harvest

# --- Load fetch snapshots to BigQuery (indexed unprocessed tables) ---
_step_begin
$PYTHON -m BigQuery.load_exchange_fetch "$OUTPUT" \
    || echo "WARN: exchange fetch load failed (non-fatal) — map falls back to JSONL"
_step_end load_fetch

# --- Write mappings ---
# Same league set as fetch (tip / LEAGUES minus BQ-optic).  MAP_LEAGUE_WORKERS
# (default 4) fans out leagues in mappers.run; STEP map_league lines land
# in the log for per-league timing.
_step_begin
$PYTHON -m mappers.run "$OUTPUT" --league $FETCH_LEAGUES --write-mappings
_step_end map

# --- Load to BigQuery ---
_step_begin
$PYTHON -m BigQuery.load_mappings "$OUTPUT/mappings.jsonl"
_step_end load

# Release the pipeline lock before post_load so the next cron tick can
# fetch/map while gap harvest still runs. post_load is best-effort and
# must not hold the 15-min slot.
flock -u 200

# --- Reconcile JSONL vs BQ fetch snapshot (best-effort; off lock path) ---
$PYTHON -m BigQuery.reconcile_fetch_snapshot "$OUTPUT" \
    || echo "WARN: fetch snapshot reconcile failed (non-fatal)"

# --- Runshop prices (best-effort; world_cup fetch only) ---
_step_begin
$PYTHON -m BigQuery.load_runshop_prices "$OUTPUT/runshop_prices.jsonl" || echo "WARN: runshop prices load failed (non-fatal)"

# Coverage gap alerts (Kalshi jsonl, Polymarket RFQ, crypto.com catalogue)
# do not run here. gap-propose drafts those repairs. Restoring the scans
# on this tick brings back the crypto.com bill (~50 TiB/day when it lived
# on */15).

# --- crypto.com tip id vs catalogue name (swapped pins) ---
$PYTHON -m BigQuery.crypto_id_name_check || echo "WARN: crypto id/name check failed (non-fatal)"
# --- crypto.com live rows vs catalogue participant (side / spread-sign flips, epic &91) ---
# End-to-end on what mmcryptocom loads; ~4 GiB/run. Critical alert on any flip;
# ALERT: lines also reach Slack through cron_pipeline.sh.
$PYTHON -m BigQuery.crypto_side_check || echo "WARN: crypto side check failed (non-fatal)"
# --- SX Bet live rows vs SX's own outcome text (side flips) ---
# Newest row per (hash, side), passthrough and constructed; SX text from this
# run's sxbet_markets.jsonl (+ /markets/find for the rest). ~45 MB/run.
# ALERT: lines reach Slack through cron_pipeline.sh.
$PYTHON -m BigQuery.sxbet_side_check "$OUTPUT" || echo "WARN: sxbet side check failed (non-fatal)"
# Gap harvest → Review runs as GKE CronJob gap-propose (mapping-console), not here.
_step_end post_load

echo "STEP name=total sec=$(( $(date +%s) - PIPELINE_T0 ))"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Pipeline complete: $OUTPUT"
