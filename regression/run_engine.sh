#!/bin/bash
# run_engine.sh SHA TICK_DIR [LEAGUE...]
#
# Produce (or reuse) the cached canonical projection of one engine
# version on one tick:
#   1. git worktree pinned to SHA (code AND config at that commit)
#   2. mappers.run TICK --json from inside the worktree
#   3. piped through project.py -> sorted canonical JSONL
#
# Cache key is (sha, tick, leagues); engine runs are ~4 min per full
# tick, diffs over cached projections are instant.  Worktrees are kept
# for reuse; `git worktree remove <dir>` (or list) to clean up.
#
# Env:
#   MM_REGRESSION_CACHE  cache root (default ~/.cache/mm-regression)
set -euo pipefail

[ $# -ge 2 ] || { echo "usage: $0 SHA TICK_DIR [LEAGUE...]" >&2; exit 2; }
SHA=$1
TICK=$(cd "$2" && pwd)          # absolute; worktree runs chdir'd away
shift 2
LEAGUES=("$@")

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
PY=$REPO/.venv/bin/python
CACHE=${MM_REGRESSION_CACHE:-$HOME/.cache/mm-regression}

SHA=$(git -C "$REPO" rev-parse --short "$SHA")
TICK_ID=$(basename "$(dirname "$TICK")")_$(basename "$TICK")
LEAGUE_ID=$(IFS=-; echo "${LEAGUES[*]:-all}")
# The comparison-contract version keys the cache: a contract bump in
# project.py invalidates every cached projection, so stale canonical
# files can never be diffed against fresh ones.
VER=$(cd "$REPO" && "$PY" -c \
    "from regression.project import VERSION; print(VERSION)")
# MM_REGRESSION_TAG (live_gate.py sets it to the pinned rules tip) joins
# the cache key when set: the same SHA on the same tick classifies
# differently under a different tip, so one tip's projection must never
# be reused under another.  Unset = the historical name bless/gate use.
TAG=${MM_REGRESSION_TAG:+.t$MM_REGRESSION_TAG}
OUT=$CACHE/canon/$SHA.$TICK_ID.$LEAGUE_ID$TAG.v$VER.jsonl
LOG=${OUT%.jsonl}.log
# The engine's full --json output, kept for the invariants (invariants.py
# needs the venue blocks the projection drops).
RAW=${OUT%.jsonl}.raw.jsonl
mkdir -p "$CACHE/canon" "$CACHE/wt"

if [ -s "$OUT" ] && [ -s "$RAW" ]; then
    echo "cached: $OUT"
    exit 0
fi

WT=$CACHE/wt/$SHA
[ -d "$WT" ] || git -C "$REPO" worktree add --detach "$WT" "$SHA" >/dev/null

# ${arr[@]+...} guards the expansion: macOS /bin/bash (3.2) treats an
# empty array as UNSET, so a bare "${arr[@]}" dies under `set -u`.
LEAGUE_ARGS=()
[ $# -gt 0 ] && LEAGUE_ARGS=(--league "$@")

cd "$WT"
# Build to a temp file and rename: an interrupted run must never
# leave a partial file where the cache check would trust it.
"$PY" -m mappers.run "$TICK" --json ${LEAGUE_ARGS[@]+"${LEAGUE_ARGS[@]}"} 2>"$LOG" \
    > "$RAW.tmp"
"$PY" "$HERE/project.py" < "$RAW.tmp" > "$OUT.tmp" 2>>"$LOG"
mv "$RAW.tmp" "$RAW"
mv "$OUT.tmp" "$OUT"
echo "built: $OUT ($(wc -l < "$OUT" | tr -d ' ') rows)"
