#!/usr/bin/env bash
# Cron wrapper for run_pipeline.sh.
# Runs the pipeline, and on failure posts the last 20 log lines to Slack.
#
# Alerts go through send_cron_alert (infra/slack_webhook.sh): Pub/Sub to
# ALERT_SLACK_CHANNEL, falling back to the ~/.slack_webhook_url webhook.
#
# Schedule lives in infra/crontab (installed on deploy):
#   */15 * * * * $HOME/mmmapper/infra/cron_pipeline.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../logs"
LOG_FILE="$LOG_DIR/pipeline.log"
# shellcheck source=infra/slack_webhook.sh
. "$SCRIPT_DIR/slack_webhook.sh"

mkdir -p "$LOG_DIR"

# Capture THIS run's output separately while still appending to the
# cumulative log.  Alerting must only ever read the per-run capture:
# grepping the cumulative log re-posted stale ALERT lines from earlier
# runs on every later successful (or skipped) tick, so a one-off warning
# looked like a recurring failure.
RUN_OUT="$(mktemp)"
trap 'rm -f "$RUN_OUT"' EXIT

"$SCRIPT_DIR/run_pipeline.sh" 2>&1 | tee -a "$LOG_FILE" > "$RUN_OUT"
EXIT_CODE="${PIPESTATUS[0]}"

if [ "$EXIT_CODE" -eq 0 ]; then
    # Pipeline succeeded — still warn if verify_source_ids flagged an
    # Optic data-quality issue (e.g. wrong-series Kalshi source_ids).
    # head -40 keeps a pathological run from blowing Slack's payload cap.
    ALERTS="$(grep '^ALERT:' "$RUN_OUT" | head -40 || true)"
    if [ -n "$ALERTS" ]; then
        send_cron_alert warning "Pipeline alert (run succeeded)" "$ALERTS" "$LOG_FILE"
    fi
    exit 0
fi

# --- Pipeline failed — notify Slack ---

# The tail alone is usually cleanup progress noise, not the failure: a
# crypto guard ValueError once alerted as 20 lines of "Stale crypto
# symbol". Lead with this run's traceback and FATAL lines so the cause
# is in the message, and keep the tail underneath for context.
CAUSE="$(grep -E '^(FATAL|Traceback|[A-Za-z_.]+(Error|Exception):)' "$RUN_OUT" | tail -5)"
TAIL="$(tail -20 "$RUN_OUT")"
if [ -n "$CAUSE" ]; then
    BODY="$CAUSE

--- last 20 lines ---
$TAIL"
else
    BODY="$TAIL"
fi
send_cron_alert critical "Pipeline failed (exit ${EXIT_CODE})" "$BODY" "$LOG_FILE"

exit "$EXIT_CODE"
