#!/usr/bin/env bash
# Fetch + map + load ONE league only, on demand — for getting a newly-wired
# or newly-aliased league live without waiting for the next 15-min tick.
#
# Shares run_pipeline.sh's own pipeline.lock and BLOCKS (waits) for it rather
# than skipping, since this is a one-off on-demand run where waiting is safe
# (unlike run_pipeline.sh's own non-blocking skip, which exists because a
# 15-min cadence must never queue behind a slower tick). Directory selection
# happens AFTER lock acquisition, on purpose: `fetch/__main__.py` always
# creates a brand-new timestamped directory per invocation, so picking the
# "latest" directory before the lock is held risked reading/writing into the
# SAME directory a concurrent run_pipeline.sh tick was still using — which
# corrupted a JSONL file mid-write and crashed that tick (root-caused and
# fixed here: this script must never touch a directory a fetch is racing on,
# so it only picks one once it holds the lock that guarantees no other fetch
# is in flight).
#
# Usage: infra/run_single_league.sh <league> [optic_horizon_hours]

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_DIR"

LOCK_FILE="$REPO_DIR/logs/pipeline.lock"
mkdir -p "$REPO_DIR/logs"
exec 200>"$LOCK_FILE"
echo "Waiting for pipeline lock (shared with run_pipeline.sh)..."
flock 200
echo "Lock acquired."

# Load .env (GCP_PROJECT etc.) — same parsing as run_pipeline.sh.
if [ -f .env ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$key=$value"
    done < .env
fi

LEAGUE="${1:?Usage: $0 <league> [optic_horizon_hours]}"
OPTIC_HOURS="${2:-${OPTIC_HOURS:-}}"

PYTHON=".venv/bin/python"
export PYTHONUNBUFFERED=1

$PYTHON -c "
from mappers.run import LEAGUES
import sys
league = sys.argv[1]
if league not in LEAGUES:
    print(f'FATAL: {league!r} is not a registered league. Known: {sorted(LEAGUES)}', file=sys.stderr)
    sys.exit(1)
" "$LEAGUE"

# Reuse the latest existing data directory (from the last regular tick)
# rather than creating a new one -- only safe now that the lock is held,
# guaranteeing no concurrent fetch is writing into it.
DIR="$(ls -td data/20*/*/ 2>/dev/null | head -1 || true)"
DIR="${DIR%/}"
if [ -z "$DIR" ]; then
    echo "FATAL: no existing data directory found under data/ -- run the regular pipeline at least once first" >&2
    exit 1
fi

echo "GCP_PROJECT=${GCP_PROJECT:-unset}"
echo "Using data dir: $DIR"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — single-league pipeline start: $LEAGUE"

OPTIC_ARGS=(--league "$LEAGUE" --out-dir "$DIR")
if [ -n "$OPTIC_HOURS" ]; then
    OPTIC_ARGS+=(--horizon-hours "$OPTIC_HOURS")
fi

$PYTHON -m fetch.optic "${OPTIC_ARGS[@]}"
$PYTHON -m fetch.kalshi --league "$LEAGUE" --out-dir "$DIR"
$PYTHON -m mappers.run "$DIR" --league "$LEAGUE" --write-mappings
$PYTHON -m BigQuery.load_mappings "$DIR/mappings.jsonl"

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — single-league pipeline complete: $LEAGUE ($DIR)"
