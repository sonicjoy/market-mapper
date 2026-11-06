"""One-off audit: current engine vs the hand-verified gold files.

The harness is otherwise purely relative (engine A vs engine B), so
it is structurally blind to mappings that have ALWAYS been wrong.
The gold files are the corpus's only human-verified truth — engine
output captured with ``mappers.run --gold`` and then earned trust
"through actual betting success" (mappers/run.py) — so before step 3
freezes current-main projections as baselines, this audit checks
current main against them once.  After triage, the gold mechanism is
retired (decision 2026-08-07, regression/HISTORY.md).

Method: for each corpus tick with a ``gold/<league>.jsonl``, re-run
the CURRENT engine with ``--gold`` into a scratch copy of the tick
(symlinks, minus ``gold/`` so the never-overwrite guard doesn't
fire) and compare old vs new gold files directly.  Both sides are
written by the engine's own ``pipeline.gold_row`` — same 12 fields,
same normalization — so there is no hand-written transcription of
the gold format here to get wrong.

Each row is keyed by its 8-field bet identity (league is the file
name); the four id fields (optic_id, px_line_id, kalshi_ticker,
kalshi_side) are the stamp.  Buckets per league file:

  matched     same key, same ids
  restamped   same key, different ids  -> triage: which id moved
  gold_only   hand-verified bet the current engine no longer emits
  new_only    current engine emits a bet gold never had (config
              growth since Mar/Apr capture is the expected cause)

Every non-matched row is written to the report dir as JSONL for
triage; each mismatch is a hand-blessing error, a legitimate config
change since capture, or a real long-standing bug.

Runs the engine from THIS working tree (verified identical to main
for mappers/ and config/ before the audit).  Subprocess only — the
no-imports-from-mappers rule holds.

Usage:
    python -m regression.gold_audit [--limit N] [--out DIR]
"""
import argparse
import json
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

from regression.corpus import ensure_tick

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PY = REPO / ".venv" / "bin" / "python"

KEY_FIELDS = ("start_date", "home", "away", "market_type", "entity",
              "line", "side", "grouping_key")
ID_FIELDS = ("optic_id", "px_line_id", "kalshi_ticker", "kalshi_side")


def gold_ticks(manifest_toml=HERE / "manifest.toml"):
    """[(tick id, [league, ...])] for every tick with gold files."""
    doc = tomllib.loads(manifest_toml.read_text())
    out = []
    for t in doc["tick"]:
        leagues = [a[len("gold/"):-len(".jsonl")] for a in t["aux"]
                   if a.startswith("gold/")]
        if leagues:
            out.append((t["id"], sorted(leagues)))
    return out


def load_gold(path):
    """gold jsonl -> {8-field key tuple: {id field: value}}.
    Duplicate keys would make the comparison ambiguous; refuse."""
    rows = {}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        key = tuple(r[f] for f in KEY_FIELDS)
        if key in rows:
            raise ValueError(f"duplicate bet key in {path}: {key}")
        rows[key] = {f: r.get(f) for f in ID_FIELDS}
    return rows


def compare(old, new):
    """(bucket counts, [triage entries]) for two load_gold dicts."""
    counts = Counter()
    triage = []
    for key in old.keys() | new.keys():
        a, b = old.get(key), new.get(key)
        if a == b:
            counts["matched"] += 1
        elif a is None:
            counts["new_only"] += 1
            triage.append({"bucket": "new_only", "key": key, "new": b})
        elif b is None:
            counts["gold_only"] += 1
            triage.append({"bucket": "gold_only", "key": key, "gold": a})
        else:
            counts["restamped"] += 1
            moved = sorted(f for f in ID_FIELDS if a[f] != b[f])
            triage.append({"bucket": "restamped", "key": key,
                           "moved": moved, "gold": a, "new": b})
    return counts, triage


def run_engine_gold(tick_dir, leagues, scratch):
    """Re-run the current engine with --gold into a symlinked copy
    of the tick (minus gold/); return the scratch gold dir."""
    scratch.mkdir(parents=True, exist_ok=True)
    for f in tick_dir.iterdir():
        if f.is_file():
            link = scratch / f.name
            link.unlink(missing_ok=True)
            link.symlink_to(f)
    log = scratch / "engine.log"
    with open(log, "w") as lf:
        r = subprocess.run(
            [str(PY), "-m", "mappers.run", str(scratch),
             "--gold", "--league", *leagues],
            cwd=REPO, stdout=lf, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise RuntimeError(f"engine failed on {tick_dir} (see {log})")
    return scratch / "gold"


def _audit_league(tick_id, tick_dir, new_gold, lg, tf):
    """Compare one league's stored gold against the fresh run;
    write its triage lines to tf.  -> comparison counts."""
    new_path = new_gold / f"{lg}.jsonl"
    if not new_path.exists():
        # engine produced no rows for this league now
        counts = Counter(
            gold_only=len(load_gold(tick_dir / "gold" / f"{lg}.jsonl")))
        triage = [{"bucket": "league_empty_now",
                   "tick": tick_id, "league": lg}]
    else:
        counts, triage = compare(
            load_gold(tick_dir / "gold" / f"{lg}.jsonl"),
            load_gold(new_path))
    for entry in triage:
        tf.write(json.dumps(
            {"tick": tick_id, "league": lg, **entry}) + "\n")
    print(f"  {tick_id} {lg}: " + ", ".join(
        f"{k}={v}" for k, v in sorted(counts.items())),
        file=sys.stderr)
    return counts


def main():
    ap = argparse.ArgumentParser(
        description="Audit current engine against gold files.")
    ap.add_argument("--limit", type=int, default=None,
                    help="audit only the first N gold ticks")
    ap.add_argument("--skip", type=int, default=0,
                    help="skip the first N gold ticks (chunked runs; "
                         "note each chunk overwrites triage.jsonl, so "
                         "use a fresh --out per chunk)")
    ap.add_argument("--out", type=Path,
                    default=Path.home() / ".cache" / "mm-gold-audit",
                    help="report + scratch dir")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    ticks = gold_ticks()[args.skip:]
    ticks = ticks[:args.limit]
    totals = Counter()
    per_file = []
    triage_path = args.out / "triage.jsonl"
    with open(triage_path, "w") as tf:
        for tick_id, leagues in ticks:
            tick_dir = ensure_tick(tick_id)
            # the engine parses fetch time from <date>/<HH_MM> in the
            # path, so the scratch copy must mirror the tick layout
            scratch = args.out / "runs" / tick_id
            try:
                new_gold = run_engine_gold(tick_dir, leagues, scratch)
            except RuntimeError as e:
                print(f"ENGINE FAILED {tick_id}: {e}", file=sys.stderr)
                per_file.append((tick_id, "*", Counter(failed=1)))
                totals["failed_runs"] += 1
                continue
            for lg in leagues:
                counts = _audit_league(tick_id, tick_dir, new_gold,
                                       lg, tf)
                per_file.append((tick_id, lg, counts))
                totals.update(counts)

    print(f"\n== gold audit totals over {len(ticks)} ticks ==")
    for k in ("matched", "restamped", "gold_only", "new_only",
              "failed_runs"):
        print(f"  {k:12s} {totals.get(k, 0)}")
    print(f"triage detail: {triage_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
