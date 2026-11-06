#!/usr/bin/env bash
# Option B: Optic refetch + wide crypto catalogue + WC remap + BQ load.
# Use on the test VM after sourcing .env (GCP_PROJECT=marketmaking-test).
set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_DIR"

if [ -f .env ]; then
    while IFS='=' read -r key value || [ -n "$key" ]; do
        [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && export "$key=$value"
    done < .env
fi

PYTHON=".venv/bin/python"
DIR="$(ls -td data/20*/* 2>/dev/null | head -1 || true)"
OPTIC_HOURS="${OPTIC_HOURS:-168}"
CRYPTO_HOURS="${CRYPTO_HOURS:-168}"

if [ -z "$DIR" ]; then
    echo "FATAL: no data dir under data/" >&2
    exit 1
fi

echo "GCP_PROJECT=${GCP_PROJECT:-unset}"
echo "Using data dir: $DIR"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — full WC crypto reload start"

$PYTHON -m fetch.optic --league world_cup --horizon-hours "$OPTIC_HOURS" --out-dir "$DIR"
$PYTHON -m fetch.kalshi --league world_cup --out-dir "$DIR"
$PYTHON -m fetch.crypto_com --hours "$CRYPTO_HOURS" --out "$DIR/crypto_com_markets.jsonl"
$PYTHON -m mappers.run --league world_cup "$DIR" --write-mappings
$PYTHON -m BigQuery.load_mappings "$DIR/mappings.jsonl"

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — full WC crypto reload complete: $DIR"
