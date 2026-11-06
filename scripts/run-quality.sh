#!/usr/bin/env bash
# Run the shared mm-ci-templates quality gate locally (same as CI `quality` job).
# Requires: pip install -e ".[dev]"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

export GCP_PROJECT="${GCP_PROJECT:-marketmaking-test}"
export QUALITY_SRC="mappers BigQuery fetch"
export QUALITY_COV_PKG="mappers"
export QUALITY_COV_MIN="0"
export QUALITY_INTERROGATE_MIN="75"
export QUALITY_PYTEST_ARGS="tests/"

# quality.sh probes .venv/bin/ only; on Windows the venv lives in Scripts/.
# Copy gate tools into bin/ (not symlinks — Git Bash [ -x ] is flaky on .exe links).
ensure_venv_bin_shims() {
  local scripts="$REPO_ROOT/.venv/Scripts"
  local bin="$REPO_ROOT/.venv/bin"
  [ -d "$scripts" ] || return 0
  mkdir -p "$bin"
  local tool exe
  for tool in ruff bandit pip-audit interrogate pytest python; do
    for exe in "$scripts/${tool}.exe" "$scripts/$tool"; do
      [ -x "$exe" ] || continue
      # Windows may hold an open handle on a prior shim (Device or resource
      # busy).  Skip quietly when replace fails — an existing shim is fine.
      rm -f "$bin/$tool" 2>/dev/null || true
      cp -f "$exe" "$bin/$tool" 2>/dev/null || true
      break
    done
  done
}
ensure_venv_bin_shims

# Prefer bin/ (what quality.sh expects); keep Scripts/ as fallback on Windows.
export PATH="$REPO_ROOT/.venv/bin:$REPO_ROOT/.venv/Scripts:${PATH}"
export PYTHONUTF8="${PYTHONUTF8:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

TEMPLATES_REF="${MM_CI_TEMPLATES_REF:-v1.1.1}"
TEMPLATES_DIR="${MM_CI_TEMPLATES_DIR:-$REPO_ROOT/.cache/mm-ci-templates}"
QUALITY_SH="$TEMPLATES_DIR/scripts/quality.sh"

if [ ! -f "$QUALITY_SH" ]; then
  mkdir -p "$(dirname "$TEMPLATES_DIR")"
  echo "run-quality: cloning mm-ci-templates@${TEMPLATES_REF} -> $TEMPLATES_DIR"
  git clone --depth 1 -b "$TEMPLATES_REF" \
    "https://gitlab.com/whiteswandata/marketmaking/mm-ci-templates.git" \
    "$TEMPLATES_DIR"
fi

patch_check_sizes() {
  local cs="$1"
  [ -f "$cs" ] || return 0
  # Allowlist keys use forward slashes; Windows Path.relative_to() emits backslashes.
  sed -i 's/rel = str(path.relative_to(ROOT))/rel = path.relative_to(ROOT).as_posix()/' "$cs"
  # Read sources as UTF-8; the Windows default (cp1252) crashes on legitimate
  # non-Latin1 bytes (e.g. combining marks in mappers/shared.py comments).
  # Idempotent: the pattern's empty parens no longer match once rewritten.
  sed -i 's/\.read_text()/.read_text(encoding="utf-8")/g' "$cs"
}
patch_check_sizes "$TEMPLATES_DIR/scripts/check_sizes.py"

# Make bandit a real blocking gate on Windows too.  The committed baseline is
# built in CI (Linux) with forward-slash paths, but bandit on Windows emits
# backslash paths, so no baselined issue matches and every one resurfaces as
# "new".  bandit matches issues on (text, severity, cwe, confidence, fname,
# test, test_id) — NOT line numbers — so translating only the baseline's path
# separators is sufficient and stays robust across unrelated edits.  Point
# QUALITY_BANDIT_BASELINE at a translated copy (kept in gitignored .cache/).
#
# Paths stay RELATIVE (cwd is REPO_ROOT): under WSL bash the Windows-venv
# python runs via interop with a Windows cwd, so absolute /mnt/c/... paths
# would not resolve.  The separator is hardcoded to backslash (not os.sep):
# the interpreter may be Linux python, but the bandit that consumes the
# baseline is the Windows-venv bandit, which emits backslash fnames.
prepare_windows_bandit_baseline() {
  [ -d ".venv/Scripts" ] || return 0
  [ -f "bandit_baseline.json" ] || return 0
  mkdir -p ".cache"
  python - "bandit_baseline.json" ".cache/bandit_baseline_win.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as f:
    data = json.load(f)
for issue in data.get("results", []):
    if "filename" in issue:
        issue["filename"] = issue["filename"].replace("/", "\\")
data["metrics"] = {
    k.replace("/", "\\"): v for k, v in data.get("metrics", {}).items()
}
with open(dst, "w", encoding="utf-8") as f:
    json.dump(data, f)
PY
  export QUALITY_BANDIT_BASELINE=".cache/bandit_baseline_win.json"
}
prepare_windows_bandit_baseline

# quality.sh sets BIN only when [ -x .venv/bin/ruff ] — unreliable on Windows
# Git Bash; force BIN when we built shims from .venv/Scripts.
if [ -d "$REPO_ROOT/.venv/Scripts" ]; then
  PATCHED="$TEMPLATES_DIR/scripts/.quality-windows.sh"
  awk '
    /^\[ -x ".venv\/bin\/ruff" \]/ { print "BIN=\".venv/bin/\""; next }
    /gate "size guard"/ {
      print "gate \"size guard\"         ${BIN}python \".cache/mm-ci-templates/scripts/check_sizes.py\" --src \"${QUALITY_SRC}\" --allowlist \"${QUALITY_SIZE_ALLOWLIST}\""
      next
    }
    { print }
  ' "$QUALITY_SH" > "$PATCHED"
  QUALITY_SH="$PATCHED"
fi

bash "$QUALITY_SH"
