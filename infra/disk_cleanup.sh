#!/usr/bin/env bash
# Free disk by removing old fetch staging dirs under data/, data_bq/ and
# data_raw/.
#
# Mappings and exchange raw stashes load to BigQuery each run; local data/
# is a short audit window only (today only, KEEP_DAYS=0).  A full day of
# staging no longer fits beside yesterday on the VM disk.  Runs nightly via
# cron_disk_cleanup.sh (installed on deploy); can also be run manually when
# the VM disk is full or before a compress backfill.
#
# Usage:
#   KEEP_SINCE=2026-07-09 bash infra/disk_cleanup.sh
#   KEEP_DAYS=0 bash infra/disk_cleanup.sh   # default: today only

set -euo pipefail

DATA_DIR="${DATA_DIR:-$HOME/mmmapper/data}"
# BQ-optic pipeline's staging root (infra/run_pipeline_bq.sh) — same <date>/
# layout as data/, kept separate so the two pipelines can't collide on a
# minute-bucket dir. Pruned on the same retention as data/.
BQ_DATA_DIR="${BQ_DATA_DIR:-$HOME/mmmapper/data_bq}"
RAW_DIR="${RAW_DIR:-$HOME/mmmapper/data_raw}"
LOG_DIR="${LOG_DIR:-$HOME/mmmapper/logs}"
KEEP_DAYS="${KEEP_DAYS:-0}"
# Exit non-zero (so the cron wrapper Slack-alerts) when the disk is still
# this low after cleanup — retention alone no longer fits the disk.
MIN_FREE_GB="${MIN_FREE_GB:-5}"

if [ -n "${KEEP_SINCE:-}" ]; then
  cutoff="$KEEP_SINCE"
else
  cutoff="$(date -u -d "${KEEP_DAYS} days ago" +%Y-%m-%d)"
fi

echo "=== disk before ==="
df -h /

# Date-stamped staging dirs (YYYY-MM-DD) older than the cutoff.
removed=0
for dir in "$DATA_DIR" "$BQ_DATA_DIR" "$RAW_DIR"; do
  [ -d "$dir" ] || continue
  cd "$dir"
  for d in 20*; do
    [ -d "$d" ] || continue
    if [[ "$d" < "$cutoff" ]]; then
      sz=$(du -sh "$d" | cut -f1)
      echo "removing $dir/$d ($sz)"
      rm -rf "$d"
      removed=$((removed + 1))
    fi
  done
done

# Cron logs append forever; keep the tail when any gets large.
for name in pipeline.log kalshi_raw.log polymarket_bridge.log \
            polymarket_token_resolutions.log ai_validation.log cron_compress.log; do
  LOG="$LOG_DIR/$name"
  [ -f "$LOG" ] || continue
  log_bytes=$(stat -c%s "$LOG")
  if [ "$log_bytes" -gt 52428800 ]; then
    echo "truncating $name ($(( log_bytes / 1048576 ))MB -> 10MiB tail)"
    tail -c 10485760 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
  fi
done

# Stale lock from a crashed run blocks cron ticks until cleared.
LOCK="$LOG_DIR/pipeline.lock"
if [ -f "$LOCK" ]; then
  if flock -n 9>"$LOCK" 2>/dev/null; then
    exec 9>&-
    rm -f "$LOCK"
    echo "cleared stale pipeline.lock"
  else
    echo "pipeline.lock held by active run — leaving in place"
  fi
fi

echo "removed $removed date directories (kept >= $cutoff)"
echo "=== disk after ==="
df -h /

avail_kb=$(df --output=avail -k / | tail -1 | tr -d ' ')
if [ "$avail_kb" -lt $(( MIN_FREE_GB * 1024 * 1024 )) ]; then
  echo "FATAL: only $(( avail_kb / 1024 / 1024 ))G free after cleanup" \
       "(< ${MIN_FREE_GB}G) — retention no longer fits the disk" >&2
  exit 1
fi
