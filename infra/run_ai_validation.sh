#!/usr/bin/env bash
# Two-hourly AI validation of our Kalshi / Polymarket / crypto.com mappings:
# judge every mapping in the fixture window that has no verdict yet and MERGE
# the results into markets_us.market_mapping_ai_validation.  Runs as its own
# cron, deliberately NOT inside run_pipeline.sh — it must never delay or fail a
# 15-minute mapping tick.  Exits non-zero on failure so cron_ai_validation.sh
# reports it.
#
# Cost is bounded by the anti-join (a mapping is judged once ever, unless
# PROMPT_VERSION is bumped) plus the corroboration skip, so a normal run only
# spends on mappings that appeared since the last one.  AI_MAX_ROWS caps a run
# hard when a backlog needs draining in slices.
#
# Schedule lives in infra/crontab (installed on deploy):
#   0 */2 * * * $HOME/mmmapper/infra/cron_ai_validation.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Load .env (GCP_PROJECT etc.) — essential for cron, which has no user
# environment.  Parses KEY=VALUE only; won't execute arbitrary shell in .env.
# The `|| [ -n "$key" ]` guard processes a final line with no trailing newline.
if [ -f .env ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$key=$value"
    done < .env
fi

# Serialize runs.  A slow run must never overlap the next tick and double-spend
# on the same rows (both would see them as unjudged); a skip exits 0 so it does
# not look like a failure to cron_ai_validation.sh.
#
# flock is util-linux, so it is present on the VM but NOT on macOS.  Without the
# guard below, `flock: command not found` makes the `if !` branch true and the
# script takes the SKIP path and exits 0 — silently validating nothing, with no
# alert, forever.  A missing lock utility must degrade to "run unlocked", never
# to "pretend another run holds the lock".
LOCK_FILE="$REPO_DIR/logs/ai_validation.lock"
mkdir -p "$REPO_DIR/logs"
if command -v flock >/dev/null 2>&1; then
    exec 200>"$LOCK_FILE"
    if ! flock -n 200; then
        echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — skip: previous AI validation run still active"
        exit 0
    fi
else
    echo "WARN: flock unavailable — running without the overlap lock (expected on macOS, NOT on the VM)" >&2
fi

PYTHON=".venv/bin/python"

echo ""
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — AI validation start"

# Two explicit invocations rather than an array of optional args: under `set -u`,
# expanding an EMPTY array as "${arr[@]}" is an unbound-variable error on bash 3.2
# (what macOS ships), so the array form dies before the job starts when
# AI_MAX_ROWS is unset. Bash 5 on the VM tolerates it; this works on both.
# -u matters here: cron_ai_validation.sh appends this output to a log and, on
# failure, Slacks the last 20 lines. Block-buffered output would be lost when the
# process dies, so the alert would arrive with nothing useful in it — and a live
# run would show no progress in the log at all.
if [ -n "${AI_MAX_ROWS:-}" ]; then
    $PYTHON -u -m BigQuery.ai_validation --max-rows "$AI_MAX_ROWS"
else
    $PYTHON -u -m BigQuery.ai_validation
fi

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — AI validation complete"
