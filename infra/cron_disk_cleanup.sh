#!/usr/bin/env bash
# Cron wrapper for disk_cleanup.sh.  Prunes old data/ + data_bq/ + data_raw/
# staging dirs and oversized logs nightly, and on failure posts the last 20 log
# lines to Slack.  Mirrors cron_pipeline.sh's shape; separate log file so
# jobs don't interleave.
#
# Alerts go through send_cron_alert (infra/slack_webhook.sh): Pub/Sub to
# ALERT_SLACK_CHANNEL, falling back to the ~/.slack_webhook_url webhook.
#
# Schedule lives in infra/crontab (installed on deploy):
#   15 2 * * * $HOME/mmmapper/infra/cron_disk_cleanup.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../logs"
LOG_FILE="$LOG_DIR/disk_cleanup.log"
# shellcheck source=infra/slack_webhook.sh
. "$SCRIPT_DIR/slack_webhook.sh"

mkdir -p "$LOG_DIR"

echo "" >> "$LOG_FILE"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Disk cleanup start" >> "$LOG_FILE"
KEEP_DAYS="${KEEP_DAYS:-0}" bash "$SCRIPT_DIR/disk_cleanup.sh" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Disk cleanup complete" >> "$LOG_FILE"
    exit 0
fi

# --- Cleanup failed — notify Slack ---

send_cron_alert critical "Disk cleanup failed (exit ${EXIT_CODE})" "$(tail -20 "$LOG_FILE")" "$LOG_FILE"

exit "$EXIT_CODE"
