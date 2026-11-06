"""Bless baselines: publish canonical projections of a known-good SHA.

A baseline is the canonical comparison projection (project.py, current
contract VERSION) of one engine version on one corpus tick, published
to ``gs://rs-marketmaking-mapping/baselines/<sha>/<tick>.<leagues>.v<N>.jsonl``.
Gating a change then means projecting only the CANDIDATE SHA and
diffing against the stored baseline — the old engine never re-runs.

Baselines are a cache with provenance, not an archive: each file is a
pure function of (sha, config-at-sha, tick, contract version), so they
can be regenerated or extended at will.  The contract version is part
of the filename — a contract bump orphans old baselines rather than
letting them be diffed against new projections.

Blessing validity rests on the gold audit (2026-08-10, see HISTORY.md):
current main reproduced 973k hand-verified gold rows before its
output was frozen as the reference here.

Usage:
    python -m regression.bless --smoke [--sha main]
    python -m regression.bless --full  [--sha main]   # 179 ticks, hours
    python -m regression.bless TICK [TICK...]

Engine runs go through run_engine.sh (SHA-pinned worktrees, cached
projections), so re-running after an interruption skips completed
ticks.  This module must not import from mappers/ or BigQuery/.
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import tomllib

from fetch.gcloud_util import gcloud_cmd
from regression.build_manifest import BUCKET
from regression.corpus import (cache_root, ensure_tick,
                               read_sha256_manifest, tier_ticks)
from regression.project import VERSION

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def canon_path(sha, tick_id):
    """The cached projection path run_engine.sh produces (leagues=all)."""
    cache = Path(os.environ.get("MM_REGRESSION_CACHE",
                                Path.home() / ".cache" / "mm-regression"))
    tick_flat = tick_id.replace("/", "_")
    return cache / "canon" / f"{sha}.{tick_flat}.all.v{VERSION}.jsonl"


def run_engine(sha, tick_dir):
    """Run run_engine.sh; Windows must launch Git Bash as the process image."""
    script = str(HERE / "run_engine.sh")
    if os.name == "nt":
        bash = os.environ.get("GIT_BASH", r"C:\Program Files\Git\bin\bash.exe")
        cmd = [bash, script, sha, tick_dir]
    else:
        cmd = [script, sha, tick_dir]
    subprocess.run(cmd, check=True, stdout=sys.stderr)


def bless_tick(sha, tick_id, manifest, root):
    """Ensure tick, build (or reuse) its projection at sha, upload."""
    tick_dir = ensure_tick(tick_id, root=root, manifest=manifest)
    run_engine(sha, str(tick_dir))
    src = canon_path(sha, tick_id)
    if not src.is_file():
        raise RuntimeError(f"expected projection missing: {src}")
    dest = f"{BUCKET.rsplit('/', 1)[0]}/baselines/{sha}/{src.name.split('.', 1)[1]}"
    subprocess.run(gcloud_cmd("storage", "cp",
                              "--no-user-output-enabled", str(src), dest),
                   check=True)
    print(f"  blessed {tick_id} -> {dest}", file=sys.stderr)


POINTER = HERE / "baselines.toml"
POINTER_HEADER = """\
# Blessed baseline per tier: the distinguished "A" the gate diffs
# against (README: the model, layer 3).  Git owns this pointer —
# bless.py rewrites it, and committing the change IS the re-bless
# event: delete the waivers that re-bless absorbs in the same
# commit.  `contract` is the project.py VERSION the baselines were
# projected under; the gate refuses a mismatch (re-bless instead).
"""


def update_pointer(tier, sha):
    """Rewrite baselines.toml with this tier -> (sha, VERSION),
    preserving other tiers.  Committing the result is the human's
    re-bless act — bless.py never touches git."""
    entries = {}
    if POINTER.exists():
        entries = tomllib.loads(POINTER.read_text())
    entries[tier] = {"sha": sha, "contract": VERSION}
    lines = [POINTER_HEADER]
    for t in sorted(entries):
        if not re.fullmatch(r"[a-z_]+", t):
            raise ValueError(f"unexpected tier name {t!r}")
        lines += [f"[{t}]", f'sha = "{entries[t]["sha"]}"',
                  f"contract = {entries[t]['contract']}", ""]
    POINTER.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(
        description="Publish baseline projections of a known-good SHA.")
    ap.add_argument("ticks", nargs="*", metavar="TICK")
    tier = ap.add_mutually_exclusive_group()
    tier.add_argument("--smoke", action="store_true")
    tier.add_argument("--full", action="store_true")
    ap.add_argument("--sha", default="main",
                    help="engine version to bless (default: main)")
    args = ap.parse_args()

    sha = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short", args.sha],
        check=True, capture_output=True, text=True).stdout.strip()
    ticks = list(args.ticks)
    if args.smoke:
        ticks += tier_ticks("smoke")
    if args.full:
        ticks += tier_ticks("full")
    if not ticks:
        ap.error("nothing to bless: give TICK ids or --smoke/--full")

    root, why = cache_root()
    print(f"blessing {len(ticks)} ticks at {sha} (contract v{VERSION}); "
          f"corpus cache {root} [{why}]", file=sys.stderr)
    manifest = read_sha256_manifest()
    for tick_id in dict.fromkeys(ticks):
        bless_tick(sha, tick_id, manifest, root)
    print(f"done: {BUCKET.rsplit('/', 1)[0]}/baselines/{sha}/",
          file=sys.stderr)
    if args.smoke or args.full:
        tier = "smoke" if args.smoke else "full"
        update_pointer(tier, sha)
        print(f"updated {POINTER} [{tier}] -> {sha}; COMMIT it — "
              f"that commit is the re-bless event (delete the "
              f"waivers it absorbs in the same commit)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
