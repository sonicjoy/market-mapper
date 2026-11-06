#!/usr/bin/env bash
# Cron wrapper for run_itf_synth.sh (synthetic-fixture job).  On failure posts
# the last 20 log lines to Slack.  Mirrors cron_kalshi_raw.sh; separate log file
# so the jobs don't interleave.
#
# Alerts go through send_cron_alert (infra/slack_webhook.sh): Pub/Sub to
# ALERT_SLACK_CHANNEL, falling back to the ~/.slack_webhook_url webhook.
#
# Schedule lives in infra/crontab (installed on deploy):
#   10-59/15 * * * * $HOME/mmmapper/infra/cron_itf_synth.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../logs"
LOG_FILE="$LOG_DIR/synthetic.log"
# shellcheck source=infra/slack_webhook.sh
. "$SCRIPT_DIR/slack_webhook.sh"

mkdir -p "$LOG_DIR"

"$SCRIPT_DIR/run_itf_synth.sh" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    exit 0
fi

# --- Job failed — notify Slack ---

send_cron_alert critical "Synthetic-fixture job failed (exit ${EXIT_CODE})" "$(tail -20 "$LOG_FILE")" "$LOG_FILE"

exit "$EXIT_CODE"
