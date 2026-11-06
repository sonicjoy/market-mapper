#!/usr/bin/env bash
# Compress .jsonl files in $DATA_DIR older than 1 day with bzip2.
#
# Date-level retention is cron_disk_cleanup.sh (today only, KEEP_DAYS=0);
# this shrinks jsonl still on disk within that window.  bzip2 writes <file>.bz2
# atomically before removing the source.
#
# Concurrency is guarded by flock so a long backfill run cannot overlap
# with the next nightly fire.
#
# Schedule lives in infra/crontab (installed on deploy):
#   30 3 * * * $HOME/mmmapper/infra/cron_compress_old_jsonl.sh
#
# For testing, override DATA_DIR (and optionally LOG / LOCK) to point at
# a single hour directory:
#   DATA_DIR=$HOME/mmmapper/data/2026-03-19/15_19 \
#   LOG=/tmp/compress_test.log LOCK=/tmp/compress_test.lock \
#       $HOME/mmmapper/infra/cron_compress_old_jsonl.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

DATA_DIR="${DATA_DIR:-$HOME/mmmapper/data}"
LOG="${LOG:-$SCRIPT_DIR/../logs/cron_compress.log}"
LOCK="${LOCK:-$SCRIPT_DIR/../logs/cron_compress.lock}"

mkdir -p "$(dirname "$LOG")" "$(dirname "$LOCK")"

exec >>"$LOG" 2>&1
echo "=== $(date -Is) start DATA_DIR=$DATA_DIR ==="

# -n: bail out immediately if another run still holds the lock (e.g. the
# initial backfill is still running when the next nightly fires).
exec 9>"$LOCK"
flock -n 9 || { echo "another run still holds the lock, exiting"; exit 0; }

# nice + ionice keep this off the back of the hourly mmmapper pipeline.
# -n 50 amortises fork cost without piling too many files per bzip2.
# gold/*.jsonl is excluded — those are the curated outputs we want kept
# directly readable.
find "$DATA_DIR" -type f -name '*.jsonl' -mtime +1 -not -path '*/gold/*' -print0 \
    | xargs -0 -r -n 50 nice -n 19 ionice -c3 bzip2 -q

echo "=== $(date -Is) done ==="
