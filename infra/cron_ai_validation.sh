#!/usr/bin/env bash
# Cron wrapper for run_ai_validation.sh.
# Runs the validator, and on failure posts the last 20 log lines to Slack.
# Mirrors cron_kalshi_raw.sh's shape; separate log file so the jobs don't
# interleave.  Flagged mappings are NOT reported here — the job publishes its
# own application-alerts rollup (BigQuery/alerts.py); this wrapper only reports
# the job dying.
#
# Expects the Slack webhook URL in ~/.slack_webhook_url (one line, no trailing
# newline).
#
# Schedule lives in infra/crontab (installed on deploy):
#   0 */2 * * * $HOME/mmmapper/infra/cron_ai_validation.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../logs"
LOG_FILE="$LOG_DIR/ai_validation.log"
# shellcheck source=infra/slack_webhook.sh
. "$SCRIPT_DIR/slack_webhook.sh"

mkdir -p "$LOG_DIR"

"$SCRIPT_DIR/run_ai_validation.sh" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    exit 0
fi

# --- Validation run failed — notify Slack ---

send_cron_alert critical "AI mapping validation failed (exit ${EXIT_CODE})" "$(tail -20 "$LOG_FILE")" "$LOG_FILE"

exit "$EXIT_CODE"
