#!/usr/bin/env bash
# Warn if the AI-validation Gemini secret is missing or unreadable in
# GCP_PROJECT.  Called from infra/deploy.sh after ensure_env (warn-only).
#
# Mirrors infra/verify_runshop_secrets.sh: every credential the VM needs is
# checked at deploy time, so a missing grant shows up in the deploy log rather
# than as a Slack failure at the next 05:20/17:20 UTC cron tick.
#
# Warn-only on purpose: the mapping pipeline must still deploy when only the
# validator's credential is absent — the 15-minute tick is the critical job.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"
PROJECT="${1:-}"

if [ -z "$PROJECT" ] && [ -f "$ENV_FILE" ]; then
    PROJECT="$(grep -E '^GCP_PROJECT=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
fi

if [ -z "$PROJECT" ]; then
    echo "verify_ai_validation_secrets: no GCP_PROJECT; skipping" >&2
    exit 0
fi

if ! command -v gcloud >/dev/null 2>&1; then
    echo "verify_ai_validation_secrets: gcloud not found; skipping" >&2
    exit 0
fi

# Keep in lockstep with GEMINI_SECRET in BigQuery/ai_validation.py.
SECRETS=(
    mm-mapping-bot-gemini-key
)

for s in "${SECRETS[@]}"; do
    if ! gcloud secrets versions access latest \
        --secret="$s" --project="$PROJECT" >/dev/null 2>&1; then
        echo "WARN: missing/unreadable secret $s in $PROJECT" \
             "— AI validation (infra/cron_ai_validation.sh) will fail" >&2
    fi
done
