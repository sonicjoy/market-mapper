#!/usr/bin/env bash
# Warn if Runshop GCP secrets are missing or unreadable in GCP_PROJECT.
# Called from infra/deploy.sh after ensure_env (warn-only).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"
PROJECT="${1:-}"

if [ -z "$PROJECT" ] && [ -f "$ENV_FILE" ]; then
    PROJECT="$(grep -E '^GCP_PROJECT=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
fi

if [ -z "$PROJECT" ]; then
    echo "verify_runshop_secrets: no GCP_PROJECT; skipping" >&2
    exit 0
fi

if ! command -v gcloud >/dev/null 2>&1; then
    echo "verify_runshop_secrets: gcloud not found; skipping" >&2
    exit 0
fi

SECRETS=(
    runshop_txodds_fusion_db_password
    runshop_poly_db_password
    runshop_betbuilder_api_key
)

for s in "${SECRETS[@]}"; do
    if ! gcloud secrets versions access latest \
        --secret="$s" --project="$PROJECT" >/dev/null 2>&1; then
        echo "WARN: missing/unreadable secret $s in $PROJECT" >&2
    fi
done
