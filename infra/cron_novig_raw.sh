#!/usr/bin/env bash
# Cron wrapper for run_novig_raw.sh.
# Runs the raw-stash, and on failure posts the last 20 log lines to
# Slack.  Mirrors cron_kalshi_raw.sh's shape; separate log file so the
# jobs don't interleave.
#
# Alerts go through send_cron_alert (infra/slack_webhook.sh): Pub/Sub to
# ALERT_SLACK_CHANNEL, falling back to the ~/.slack_webhook_url webhook.
#
# Schedule lives in infra/crontab (installed on deploy):
#   2,17,32,47 * * * * $HOME/mmmapper/infra/cron_novig_raw.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../logs"
LOG_FILE="$LOG_DIR/novig_raw.log"
# shellcheck source=infra/slack_webhook.sh
. "$SCRIPT_DIR/slack_webhook.sh"

mkdir -p "$LOG_DIR"

# Run the raw-stash, appending to the log.
"$SCRIPT_DIR/run_novig_raw.sh" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    exit 0
fi

# --- Raw-stash failed — notify Slack ---

send_cron_alert critical "Novig raw-stash failed (exit ${EXIT_CODE})" "$(tail -20 "$LOG_FILE")" "$LOG_FILE"

exit "$EXIT_CODE"
