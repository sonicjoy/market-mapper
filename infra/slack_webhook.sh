#!/usr/bin/env bash
# Shared Slack webhook resolution for the cron alert wrappers.
#
# Routes alerts from a *-test host (e.g. market-mapping-test) to a separate
# channel when a per-env webhook file is present, so prod and test alerts do
# not share one channel. Falls back to the default webhook when the per-env
# file is absent, so a host without it keeps alerting rather than going silent.
#
# Prereq to activate test routing: put the test channel's incoming-webhook URL
# in ~/.slack_webhook_url_test on the market-mapping-test host (the prod host
# keeps using ~/.slack_webhook_url).
#
# The webhook is now the FALLBACK route: send_cron_alert (below) publishes to
# Pub/Sub with ALERT_SLACK_CHANNEL first.

resolve_slack_webhook_file() {
    local default="$HOME/.slack_webhook_url"
    case "$(hostname -s)" in
        *-test)
            local test_file="$HOME/.slack_webhook_url_test"
            if [ -f "$test_file" ]; then
                printf '%s\n' "$test_file"
                return
            fi
            ;;
    esac
    printf '%s\n' "$default"
}

# send_cron_alert <severity> <title> <body> <log_file>
#
# Posts one cron-wrapper alert. Takes the same path as the rest of mmmapper's
# alerts first -- Pub/Sub application-alerts with ALERT_SLACK_CHANNEL, which the
# relay delivers to that channel (#marketmaking-mapping-alerts) -- and falls
# back to the host's incoming webhook when that route is not configured
# (ALERT_PUBSUB_ENABLED off or ALERT_SLACK_CHANNEL empty in .env) or the
# publish fails, so a host never goes silent.
#
# <severity> is info|warning|critical; <title> is the one-line headline and
# <body> goes in a code block underneath.
send_cron_alert() {
    local severity="$1" title="$2" body="$3" log_file="$4"
    local repo_dir host ts text
    repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    host="$(hostname -s)"
    ts="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    text="*${title}* on \`${host}\` at ${ts}
\`\`\`
${body}
\`\`\`"

    # Subshell: .env is loaded for the publisher only, not into the wrapper.
    # KEY=VALUE lines only, same parse as the run_*.sh scripts.
    if (
        cd "$repo_dir" || exit 1
        if [ -f .env ]; then
            while IFS='=' read -r key value || [ -n "$key" ]; do
                [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$key=$value"
            done < .env
        fi
        printf '%s' "$text" | timeout 60 .venv/bin/python -m BigQuery.alerts --severity "$severity"
    ) >> "$log_file" 2>&1; then
        return 0
    fi

    local webhook_file emoji payload
    webhook_file="$(resolve_slack_webhook_file)"
    if [ ! -f "$webhook_file" ]; then
        echo "${ts} — ${title} and no alert route: Pub/Sub not routable, no webhook file at ${webhook_file}" >> "$log_file"
        return 0
    fi
    case "$severity" in
        critical) emoji=":red_circle:" ;;
        warning) emoji=":warning:" ;;
        *) emoji=":information_source:" ;;
    esac
    # JSON-escape backslashes, quotes and newlines for the webhook body.
    payload="$(printf '%s %s' "$emoji" "$text" \
        | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' \
        | awk 'BEGIN { ORS = "" } NR > 1 { print "\\n" } { print }')"
    curl -sf -o /dev/null -X POST \
        -H 'Content-type: application/json' \
        -d "{\"text\": \"${payload}\"}" \
        "$(cat "$webhook_file")" \
        2>> "$log_file" || true
}
