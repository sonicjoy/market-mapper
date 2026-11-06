#!/usr/bin/env bash
# BQ-sourced mapping pipeline for lower-tier soccer leagues.
#
# Unlike infra/run_pipeline.sh (which fetches Optic fixtures+odds from the
# OpticOdds API), this variant reads Optic from BigQuery
# (opticodds_us.opticodds_fixtures + opticodds_prices via
# BigQuery.optic_from_bq). Use it for leagues whose fixtures are NOT on the
# API-fetch subscription but whose streaming odds ARE in BQ.
#
# fetch.polymarket and Kalshi are fetched normally: poly jsonl is a BQ
# read of raw_ingestion_us.polymarket_position_token_bridge (rebuilt by
# the independent cron_polymarket_bridge.sh, not this script). Kalshi's
# series live on its own API regardless of where Optic fixtures come from
# — china_super / peru_primera / norway_eliteserien all have live
# KX*GAME/SPREAD/TOTAL/BTTS series, and without this step their
# KalshiConfigs could never fire.
# Steps: optic-from-BQ -> fetch.polymarket -> kalshi -> map -> load.
#
# NOT SCHEDULED as of 2026-08-14 — this script is MANUAL-ONLY.  Its crontab
# entry was removed on an explicit call, because BigQuery.optic_from_bq scans
# ~148.9M opticodds_prices rows per tick to use ~9.4M of them (no league or
# fixture predicate) and it ran 96x/day.  BQ_OPTIC_LEAGUES was removed
# 2026-08-25 (those leagues are on the main API fetch). Emergency one-off:
#
#   BQ_LEAGUES='china_super_league …' GCP_PROJECT=marketmaking-test \
#     infra/run_pipeline_bq.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Serialize runs of THIS pipeline, exactly as run_pipeline.sh does for its own.
# The lock file is deliberately DIFFERENT from pipeline.lock: the two pipelines
# cover disjoint league sets and must be able to overlap (they are offset by 5
# minutes, but the BQ optic pull is unbounded in duration). Sharing a lock
# would let a slow API tick silently starve every BQ league — the exact
# never-runs failure this script's schedule was added to fix.
#
# Non-blocking by default so ticks can never queue up unboundedly; exiting 0
# keeps a skip from looking like a failure to cron_pipeline_bq.sh. A deploy
# sets PIPELINE_LOCK_WAIT to wait for the active run instead, so freshly
# deployed config goes live promptly.
LOCK_WAIT="${PIPELINE_LOCK_WAIT:-0}"
LOCK_FILE="$REPO_DIR/logs/pipeline_bq.lock"
mkdir -p "$REPO_DIR/logs"
exec 200>"$LOCK_FILE"
if [ "$LOCK_WAIT" -gt 0 ]; then
    if ! flock -w "$LOCK_WAIT" 200; then
        echo "FATAL: could not acquire BQ pipeline lock within ${LOCK_WAIT}s" >&2
        exit 1
    fi
else
    if ! flock -n 200; then
        echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — skip: previous BQ pipeline run still active"
        exit 0
    fi
fi

# Keep stdout in step with stderr in the log, so a traceback doesn't land ahead
# of the prints that preceded it (same reason as run_pipeline.sh).
export PYTHONUNBUFFERED=1

if [ -f .env ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$key=$value"
    done < .env
fi

: "${GCP_PROJECT:?set GCP_PROJECT (e.g. marketmaking-test)}"
PYTHON=".venv/bin/python"

# No default league list — BQ_OPTIC_LEAGUES was removed 2026-08-25.
if [ -z "${BQ_LEAGUES:-}" ]; then
    echo "FATAL: BQ_OPTIC_LEAGUES is gone; export BQ_LEAGUES='…' for a one-off BQ pull" >&2
    exit 1
fi

# Own staging root (data_bq/), NOT the main pipeline's data/. The two crons
# share the same <date>/<HH_MM> minute layout, and the main pipeline's fetch
# orchestrator (fetch/__main__.py) DIES if its minute-bucket dir already
# exists. When a slow main-tick fetch drifted into this pipeline's offset
# minute, both landed on the same data/<date>/
# <HH_MM> and the main run failed with "already exists". Separate roots make
# the collision impossible regardless of runtime drift; the leaf stays
# <date>/<HH_MM> so mappers.run still parses fetch_time from the path.
DIR="data_bq/$(date -u +%Y-%m-%d)/$(date -u +%H_%M)"
mkdir -p "$DIR"
echo "$(date -u '+%F %T UTC') — BQ pipeline start (project=$GCP_PROJECT, dir=$DIR)"
echo "  leagues: $BQ_LEAGUES"

echo "=== Optic from BigQuery ==="
$PYTHON -m BigQuery.optic_from_bq "$DIR/optic_fixtures_odds.jsonl" --sport soccer

echo "=== Polymarket bridge ==="
$PYTHON -m fetch.polymarket --out-dir "$DIR"

echo "=== Kalshi ==="
# Leagues with no KalshiConfig print "no Kalshi coverage, skipping", so the
# whole BQ_LEAGUES list is safe to pass. Optional, as in run_pipeline.sh: a
# Kalshi outage must not cost us the Optic/Polymarket mappings. The output is
# written in one final block, so a failure leaves no file — but drop it anyway
# rather than risk mapping off a truncated JSONL.
# shellcheck disable=SC2086
if ! $PYTHON -m fetch.kalshi --league $BQ_LEAGUES --out-dir "$DIR"; then
    echo "  WARNING: Kalshi fetch failed — mapping without Kalshi" >&2
    rm -f "$DIR/kalshi_markets.jsonl"
fi

echo "=== Map ==="
# shellcheck disable=SC2086
$PYTHON -m mappers.run "$DIR" --league $BQ_LEAGUES --write-mappings

echo "=== Load to BigQuery ($GCP_PROJECT.markets_us.market_mapping) ==="
# Own staging table, NOT the main pipeline's markets_us.market_mapping_stage.
# Both pipelines run on separate locks and can overlap (see infra/crontab); a
# shared stage means one run's WRITE_TRUNCATE wipes the other's batch mid-load
# and both MERGEs can INSERT the same key into market_mapping, which enforces
# no unique constraint — the 2026-08-14 duplicate-key FATAL. The target table
# stays shared (disjoint league rows, key-scoped MERGE). Only the stage must be
# private. See BigQuery/docs/staging-isolation.md.
export MAPPING_STAGE_TABLE="markets_us.market_mapping_stage_bq"
$PYTHON -m BigQuery.load_mappings "$DIR/mappings.jsonl"

echo "$(date -u '+%F %T UTC') — BQ pipeline complete: $DIR"
