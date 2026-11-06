#!/usr/bin/env bash
# Cron wrapper for run_polymarket_bridge.sh.
# Runs the combos-rfq → Gamma → BQ MERGE, and on failure posts the last
# 20 log lines to Slack.  Mirrors cron_kalshi_raw.sh; separate log so
# the mapping tick is not interleaved with catalog paging.
#
# Alerts go through send_cron_alert (infra/slack_webhook.sh): Pub/Sub to
# ALERT_SLACK_CHANNEL, falling back to the ~/.slack_webhook_url webhook.
#
# Schedule lives in infra/crontab (installed on deploy):
#   8,23,38,53 * * * * $HOME/mmmapper/infra/cron_polymarket_bridge.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../logs"
LOG_FILE="$LOG_DIR/polymarket_bridge.log"
# shellcheck source=infra/slack_webhook.sh
. "$SCRIPT_DIR/slack_webhook.sh"

mkdir -p "$LOG_DIR"

"$SCRIPT_DIR/run_polymarket_bridge.sh" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    exit 0
fi

send_cron_alert critical "Polymarket bridge failed (exit ${EXIT_CODE})" "$(tail -20 "$LOG_FILE")" "$LOG_FILE"

exit "$EXIT_CODE"
