#!/usr/bin/env bash
# Cron wrapper for run_pipeline_bq.sh (the BQ-optic-sourced leagues).
# Runs the pipeline, and on failure posts the last 20 log lines to Slack.
#
# Sibling of cron_pipeline.sh, deliberately kept as a SEPARATE cron entry
# rather than a step appended to run_pipeline.sh: the BQ pull is unbounded in
# duration (it scans opticodds_prices), and chaining it would put every
# API-fetch league's freshness behind it.
#
# Alerts go through send_cron_alert (infra/slack_webhook.sh): Pub/Sub to
# ALERT_SLACK_CHANNEL, falling back to the ~/.slack_webhook_url webhook.
#
# NO LONGER IN infra/crontab as of 2026-08-14 — the 5,20,35,50 entry was
# removed on an explicit call to stop paying for optic_from_bq's unscoped
# opticodds_prices scan.  The wrapper is kept (not deleted) so rescheduling is
# a one-line crontab change once that scan is league-scoped; see infra/crontab
# for the measured cost and the 17 leagues this leaves unmapped.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../logs"
LOG_FILE="$LOG_DIR/pipeline_bq.log"
# shellcheck source=infra/slack_webhook.sh
. "$SCRIPT_DIR/slack_webhook.sh"

mkdir -p "$LOG_DIR"

# Its own log file, not pipeline.log: the two pipelines run concurrently, and
# interleaved appends would corrupt the run-scoped awk extraction below.
"$SCRIPT_DIR/run_pipeline_bq.sh" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 0 ]; then
    exit 0
fi

# --- Pipeline failed — notify Slack ---

# Lead with this run's traceback and FATAL lines so the cause is in the
# message, and keep the tail underneath for context (same shape as
# cron_pipeline.sh; the start marker differs because run_pipeline_bq.sh
# prints "— BQ pipeline start (project=…, dir=…)").
RUN_LOG="$(awk '/— BQ pipeline start/ { buf = "" } { buf = buf $0 "\n" } END { printf "%s", buf }' "$LOG_FILE")"
CAUSE="$(echo "$RUN_LOG" | grep -E '^(FATAL|Traceback|[A-Za-z_.]+(Error|Exception):)' | tail -5)"
TAIL="$(echo "$RUN_LOG" | tail -20)"
if [ -n "$CAUSE" ]; then
    BODY="$CAUSE

--- last 20 lines ---
$TAIL"
else
    BODY="$TAIL"
fi
send_cron_alert critical "BQ pipeline failed (exit ${EXIT_CODE})" "$BODY" "$LOG_FILE"

exit "$EXIT_CODE"
