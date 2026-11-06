#!/usr/bin/env bash
# Install repo git hooks (pre-commit runs quality gate + pyright).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK_SRC="$REPO_ROOT/scripts/hooks/pre-commit"
HOOK_DST="$REPO_ROOT/.git/hooks/pre-commit"

if [ ! -d "$REPO_ROOT/.git" ]; then
  echo "install-git-hooks: not a git repository: $REPO_ROOT" >&2
  exit 1
fi

cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_SRC" "$HOOK_DST"
echo "Installed $HOOK_DST"
