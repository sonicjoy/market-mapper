"""Gate a candidate SHA against the blessed baseline.

Usage:
    python -m regression.gate CANDIDATE [--tier smoke]
    python -m regression.gate CANDIDATE TICK [TICK...]

The everyday question — "did my change move anything?" — as one
command: reads `baselines.toml` (the distinguished "A", named in
git; refuses a contract-version mismatch), materializes the tier's
ticks (verified pull), projects the candidate through
`run_engine.sh` (cached), fetches baseline projections from the
bucket (also cached, same filename scheme), and diffs each pair
under `waivers.toml`.  Exit 0 iff every tick gates clean (zero
UNEXPLAINED deltas).

This is layer 3 of the model (see README).  For an unopinionated
A/B between arbitrary SHAs, use run_engine.sh + diff.py directly —
no pointer, no waivers.
"""
import argparse
import subprocess
import sys

import tomllib

from fetch.gcloud_util import gcloud_cmd
from regression.bless import HERE, REPO, canon_path, run_engine
from regression.build_manifest import BUCKET
from regression.corpus import (cache_root, ensure_tick,
                               read_sha256_manifest, tier_ticks)
from regression.project import VERSION
from regression.waivers import WaiverError
from regression import diff


def baseline_pointer(tier, path=HERE / "baselines.toml"):
    """The blessed SHA for a tier; refuses contract mismatch."""
    doc = tomllib.loads(path.read_text())
    if tier not in doc:
        raise KeyError(
            f"no {tier!r} baseline in {path.name} — bless one first "
            f"(python -m regression.bless --{tier})")
    entry = doc[tier]
    if entry["contract"] != VERSION:
        raise RuntimeError(
            f"{tier} baseline {entry['sha']} was blessed under "
            f"contract v{entry['contract']} but the projector is "
            f"v{VERSION} — re-bless before gating")
    return entry["sha"]


def ensure_baseline(sha, tick_id):
    """Fetch one baseline projection into the projection cache
    (same path run_engine.sh would produce for that SHA) unless
    already present."""
    dest = canon_path(sha, tick_id)
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = (f"{BUCKET.rsplit('/', 1)[0]}/baselines/{sha}/"
           f"{dest.name.split('.', 1)[1]}")
    try:
        subprocess.run(gcloud_cmd("storage", "cp",
                        "--no-user-output-enabled", url, str(dest)),
                       check=True)
    except subprocess.CalledProcessError:
        raise RuntimeError(
            f"could not fetch baseline {url} — expired gcloud auth "
            f"(`gcloud auth login`)?  Or regenerate it locally: "
            f"run_engine.sh {sha} <tick dir>") from None
    return dest


def main():
    ap = argparse.ArgumentParser(
        description="Gate a candidate SHA against the blessed baseline.")
    ap.add_argument("candidate", help="SHA / ref to gate")
    ap.add_argument("ticks", nargs="*", metavar="TICK",
                    help="specific ticks (default: the tier's)")
    ap.add_argument("--tier", default="smoke")
    args = ap.parse_args()

    cand = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--short",
         args.candidate],
        check=True, capture_output=True, text=True).stdout.strip()
    base = baseline_pointer(args.tier)
    ticks = args.ticks or tier_ticks(args.tier)
    print(f"gate: {cand} vs blessed {args.tier} baseline {base} "
          f"(contract v{VERSION}), {len(ticks)} ticks", file=sys.stderr)

    root, why = cache_root()
    print(f"corpus cache: {root} [{why}]", file=sys.stderr)
    manifest = read_sha256_manifest()
    failures = []
    for tick_id in ticks:
        tick_dir = ensure_tick(tick_id, root=root, manifest=manifest)
        run_engine(cand, str(tick_dir))
        base_file = ensure_baseline(base, tick_id)
        cand_file = canon_path(cand, tick_id)
        print(f"\n--- {tick_id} ---")
        code = diff.run(str(base_file), str(cand_file),
                        waivers_path=HERE / "waivers.toml")
        if code != 0:
            failures.append(tick_id)
    if failures:
        print(f"\nGATE FAIL on {len(failures)}/{len(ticks)} ticks: "
              f"{', '.join(failures)}")
        return 1
    print(f"\nGATE PASS: {len(ticks)} ticks clean")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except WaiverError as e:
        print(e, file=sys.stderr)
        sys.exit(2)
