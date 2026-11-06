#!/usr/bin/env bash
# Idempotently ensure repo-root .env has deployment-managed keys.
#
# Called by infra/deploy.sh after each deploy. Maps GCP project (or branch
# ref) to alert Pub/Sub settings matching bf-market-listener conventions:
#   marketmaking-test -> test-application-alerts (enabled)
#   rs-marketmaking   -> application-alerts (enabled)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"
REF="${1:-}"

set_env_key() {
    local key="$1"
    local value="$2"
    local tmp
    tmp="$(mktemp)"
    if [ -f "$ENV_FILE" ]; then
        grep -v "^${key}=" "$ENV_FILE" > "$tmp" || true
    else
        : > "$tmp"
    fi
    printf '%s=%s\n' "$key" "$value" >> "$tmp"
    mv "$tmp" "$ENV_FILE"
}

read_env_key() {
    local key="$1"
    if [ ! -f "$ENV_FILE" ]; then
        return 0
    fi
    grep -E "^${key}=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true
}

gcp_project="$(read_env_key GCP_PROJECT)"

if [ -z "$gcp_project" ] && [ -n "$REF" ]; then
    case "$REF" in
        test) gcp_project="marketmaking-test" ;;
        main) gcp_project="rs-marketmaking" ;;
    esac
fi

if [ -z "$gcp_project" ] && command -v gcloud >/dev/null 2>&1; then
    gcp_project="$(gcloud config get-value project 2>/dev/null || true)"
fi

if [ -z "$gcp_project" ]; then
    echo "ensure_env: cannot determine GCP_PROJECT; skipping" >&2
    exit 0
fi

case "$gcp_project" in
    marketmaking-test)
        alert_enabled="true"
        alert_topic="test-application-alerts"
        ;;
    rs-marketmaking)
        alert_enabled="true"
        alert_topic="application-alerts"
        ;;
    *)
        echo "ensure_env: unknown GCP_PROJECT=${gcp_project}; skipping alert env" >&2
        exit 0
        ;;
esac

set_env_key GCP_PROJECT "$gcp_project"
set_env_key ALERT_PUBSUB_ENABLED "$alert_enabled"
set_env_key ALERT_PUBSUB_TOPIC "$alert_topic"

# Slack channel for these alerts. Empty = the relay's default,
# #marketmaking-alerts-rfqs, shared with every other application-alerts
# publisher. Set it in .env (e.g. "#marketmaking-mapping-alerts") to give mapping alerts
# their own channel -- but ONLY once the relay has its bot token and the bot is
# a member of that channel: chat.postMessage answers 200 with ok=false on
# not_in_channel. Re-read here so a deploy preserves the operator's value.
#
# Test is pinned to #mm-test-app-alerts so a test failure never lands in the
# prod mapping channel (2026-09-25: a market-mapping-test pipeline failure
# posted to #marketmaking-mapping-alerts). @mmalertmanager must be a member.
case "$gcp_project" in
    marketmaking-test) set_env_key ALERT_SLACK_CHANNEL "#mm-test-app-alerts" ;;
    *) set_env_key ALERT_SLACK_CHANNEL "$(read_env_key ALERT_SLACK_CHANNEL)" ;;
esac

case "$gcp_project" in
    marketmaking-test)
        # Test mapper classifies from the activated BQ tip (Flip 1+2).
        set_env_key MAPPING_SOT "bq"
        set_env_key MAPPING_CP_BOOTSTRAP "1"
        # mmmapper#24 override lane: active crypto.com overrides become
        # market_mapping rows at load. Test only; prod leaves it unset (OFF).
        set_env_key MAPPING_OVERRIDE_LANE "1"
        # STX (Ontario exchange) catalogue in the tick: the Ontario DEMO book on test (accepts any IP, so no
        # proxy). The key is read from Secret Manager (stx-api-key-id / stx-private-key).
        set_env_key STX_ENV "demo"
        set_env_key STX_REGION "ontario"
        ;;
    rs-marketmaking)
        # Prod mapper classifies from the activated BQ tip (M4 prod).
        set_env_key MAPPING_SOT "bq"
        set_env_key MAPPING_CP_BOOTSTRAP "1"
        # Taxonomy dual-read vs the served tip (audit only; never fails the tick).
        set_env_key MAPPING_DUAL_READ "1"
        # mmmapper#24 override lane (owner, 2026-09-27: supervised prod trial).
        # Revert = set "0" here and redeploy; the next run drops override rows.
        set_env_key MAPPING_OVERRIDE_LANE "1"
        # STX Ontario PRODUCTION catalogue in the tick. STX accepts Ontario source IPs only, so the STX REST calls
        # (only those, fetch/stx.py) go through the Toronto Squid stx-proxy-on on its static egress IP
        # (mm-infrastructure stx_ontario_egress.tf, prevent_destroy; it admits this VM's market-mapping-ip).
        # Off = set STX_ENV "" here and redeploy.
        set_env_key STX_ENV "prod"
        set_env_key STX_REGION "ontario"
        set_env_key STX_HTTPS_PROXY "http://34.130.95.249:3128"
        ;;
esac

echo "ensure_env: GCP_PROJECT=${gcp_project} ALERT_PUBSUB_ENABLED=${alert_enabled} ALERT_PUBSUB_TOPIC=${alert_topic} ALERT_SLACK_CHANNEL=$(read_env_key ALERT_SLACK_CHANNEL) MAPPING_SOT=$(read_env_key MAPPING_SOT) MAPPING_DUAL_READ=$(read_env_key MAPPING_DUAL_READ) MAPPING_OVERRIDE_LANE=$(read_env_key MAPPING_OVERRIDE_LANE)"
