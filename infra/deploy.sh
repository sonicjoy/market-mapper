#!/usr/bin/env bash
# Deploy mmmapper on a VM.
#
# GitLab CI ships the source as an archive, then refreshes deps and syncs git:
#   deploy.sh --refresh-deps --commit <sha> --ref <branch> --fetch-url <url>
#
# Manual / legacy (VM must reach GitLab):
#   deploy.sh <branch>
#
# Reconciles the VM crontab from infra/crontab (the schedule's single
# source of truth), then starts infra/run_pipeline.sh in the background
# (same as the scheduled cron) so new mapper config is effective soon
# without blocking deploy/CI.  Skip with DEPLOY_SKIP_PIPELINE=1.
# Log: logs/deploy-pipeline.log

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

GITLAB_ORIGIN="https://gitlab.com/whiteswandata/marketmaking/mmmapper.git"

write_deployed_marker() {
  local commit="$1"
  local ref="$2"
  cat > infra/DEPLOYED <<EOF
commit=$commit
ref=$ref
deployed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
}

scrub_origin_credentials() {
  if git remote get-url origin &>/dev/null; then
    git remote set-url origin "$GITLAB_ORIGIN"
  fi
}

sync_git_to_commit() {
  local commit="$1"
  local ref="$2"
  local fetch_url="$3"

  if [[ "$fetch_url" == *.bundle ]]; then
    git fetch "$fetch_url" "+refs/remotes/origin/${ref}:refs/heads/${ref}"
  else
    git fetch "$fetch_url" "$ref"
  fi
  git checkout -f -B "$ref" "$commit"
  scrub_origin_credentials
}

refresh_deps() {
  echo "Refreshing deps in $REPO_DIR"
  .venv/bin/pip install -q -r requirements.txt
}

ensure_env() {
  local ref="${1:-}"
  bash "$REPO_DIR/infra/ensure_env.sh" "$ref"
}

# cron_compress_old_jsonl.sh needs bzip2; bootstrap.sh installs it on new
# VMs but older VMs may lack it.
ensure_bzip2() {
  if command -v bzip2 >/dev/null 2>&1; then
    echo "ensure_bzip2: bzip2 already installed"
    return 0
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "ensure_bzip2: apt-get not available — skipping" >&2
    return 0
  fi
  echo "ensure_bzip2: installing bzip2"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq bzip2
}

# Reconcile the VM crontab from infra/crontab (the single source of truth
# for the schedule).  Idempotent: only rewrites when the current crontab
# differs, and backs up the previous one first.  Installs for the invoking
# user (deploy runs as the repo owner, gtod), so the schedule is no longer
# a hand-edited, drift-prone piece of VM state.
ensure_crontab() {
  local desired="$REPO_DIR/infra/crontab"
  if ! command -v crontab >/dev/null 2>&1; then
    echo "ensure_crontab: crontab not available — skipping"
    return 0
  fi
  if [ ! -f "$desired" ]; then
    echo "ensure_crontab: $desired missing — skipping"
    return 0
  fi
  local normalized
  normalized="$(mktemp)"
  # Strip CR (repo is edited on Windows) so cron doesn't see \r in commands.
  sed 's/\r$//' "$desired" > "$normalized"
  local current
  current="$(crontab -l 2>/dev/null || true)"
  if [ "$current" = "$(cat "$normalized")" ]; then
    echo "ensure_crontab: crontab already up to date"
    rm -f "$normalized"
    return 0
  fi
  if [ -n "$current" ]; then
    mkdir -p "$REPO_DIR/logs"
    local backup="$REPO_DIR/logs/crontab.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    printf '%s\n' "$current" > "$backup"
    echo "ensure_crontab: backed up existing crontab to $backup"
  fi
  crontab "$normalized"
  rm -f "$normalized"
  echo "ensure_crontab: installed repo-managed crontab from infra/crontab"
}

verify_runshop_secrets() {
  if command -v gcloud >/dev/null 2>&1 && [ -f "$REPO_DIR/.env" ]; then
    bash "$REPO_DIR/infra/verify_runshop_secrets.sh" || true
  fi
}

verify_ai_validation_secrets() {
  if command -v gcloud >/dev/null 2>&1 && [ -f "$REPO_DIR/.env" ]; then
    bash "$REPO_DIR/infra/verify_ai_validation_secrets.sh" || true
  fi
}

run_post_deploy_pipeline() {
  if [ "${DEPLOY_SKIP_PIPELINE:-}" = "1" ]; then
    echo "Skipping post-deploy pipeline (DEPLOY_SKIP_PIPELINE=1)"
    return 0
  fi
  echo ""
  echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') — Starting post-deploy pipeline in background"
  mkdir -p "$REPO_DIR/logs"
  # Background so deploy/CI does not wait on fetch+map+BQ.  nohup survives
  # the gcloud ssh session ending.  PIPELINE_LOCK_WAIT still waits (bounded)
  # for any in-flight cron run; cron ticks meanwhile skip via non-blocking lock.
  nohup env PIPELINE_LOCK_WAIT="${PIPELINE_LOCK_WAIT:-1800}" \
    bash "$REPO_DIR/infra/run_pipeline.sh" \
    >> "$REPO_DIR/logs/deploy-pipeline.log" 2>&1 &
  echo "Post-deploy pipeline pid $! (log: logs/deploy-pipeline.log)"
}

if [ "${1:-}" = "--refresh-deps" ]; then
  shift
  DEPLOY_COMMIT=""
  DEPLOY_REF=""
  DEPLOY_FETCH_URL=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --commit) DEPLOY_COMMIT="$2"; shift 2 ;;
      --ref) DEPLOY_REF="$2"; shift 2 ;;
      --fetch-url) DEPLOY_FETCH_URL="$2"; shift 2 ;;
      *)
        echo "Unknown option: $1" >&2
        exit 1
        ;;
    esac
  done

  refresh_deps
  ensure_env "${DEPLOY_REF:-}"
  verify_runshop_secrets
  verify_ai_validation_secrets

  if [ -n "$DEPLOY_COMMIT" ] && [ -n "$DEPLOY_REF" ] && [ -n "$DEPLOY_FETCH_URL" ]; then
    sync_git_to_commit "$DEPLOY_COMMIT" "$DEPLOY_REF" "$DEPLOY_FETCH_URL"
    write_deployed_marker "$DEPLOY_COMMIT" "$DEPLOY_REF"
    echo "Deployed $DEPLOY_COMMIT on $DEPLOY_REF (git synced)"
  elif [ -n "$DEPLOY_COMMIT" ]; then
    write_deployed_marker "$DEPLOY_COMMIT" "${DEPLOY_REF:-unknown}"
    echo "Deployed $DEPLOY_COMMIT (archive only; git not synced — pass --fetch-url)"
  else
    echo "Deployed (archive) $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  fi
  ensure_bzip2
  ensure_crontab
  run_post_deploy_pipeline
  exit 0
fi

BRANCH="${1:?usage: deploy.sh <branch> | deploy.sh --refresh-deps [--commit SHA --ref REF --fetch-url URL]}"

echo "Deploying branch: $BRANCH"
git fetch origin
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"
scrub_origin_credentials

refresh_deps
ensure_env "$BRANCH"
verify_runshop_secrets
verify_ai_validation_secrets

COMMIT="$(git rev-parse HEAD)"
write_deployed_marker "$COMMIT" "$BRANCH"
echo "Deployed $COMMIT on branch $BRANCH"
ensure_bzip2
ensure_crontab
run_post_deploy_pipeline
