"""Diff two canonical projections; report deltas bucketed for humans.

Usage: diff.py A.jsonl B.jsonl [--samples N] [--waivers FILE]

Set-diffs whole canonical lines (see project.py for the form),
buckets deltas by (league, sportsbook, market_type), prints counts
and sample rows.

Two modes (README: the model, layers 2 and 3):

- **Plain diff** (no --waivers): any A vs any B; exit 0 iff
  identical.  The unopinionated layer-2 rig.
- **Gate** (--waivers): every delta is classified WAIVED(id) or
  UNEXPLAINED per regression/waivers.py; exit 0 iff no UNEXPLAINED.
  Waived counts are printed on every run — green, never silently
  green.  Stale waivers (matched nothing) are reported for
  deletion; breached ceilings and expired waivers return their
  deltas to UNEXPLAINED, loudly.  An invalid waivers file exits 2.

A zero diff is only meaningful if the tick could have witnessed the
change — check the tick's league/exchange inventory in
manifest.toml before celebrating.
"""
import argparse
import datetime
import json
import sys
from collections import defaultdict

from regression import swaps
from regression.waivers import WaiverError, classify, load_waivers


def load(path):
    with open(path) as f:
        return set(line.strip() for line in f if line.strip())


def bucket(lines):
    """Group canonical lines by (league, sportsbook, market_type)."""
    b = defaultdict(list)
    for line in sorted(lines):
        r = json.loads(line)
        b[(r["k"][0], r["sb"], r["k"][4])].append(r)
    return b


def render(title, lines, samples, out):
    print(f"\n== {title}: {len(lines)} rows ==", file=out)
    for (league, sb, mt), rows in sorted(bucket(lines).items()):
        print(f"  {league:28s} {sb:12s} {mt:24s} {len(rows):5d}", file=out)
        for r in rows[:samples]:
            k = r["k"]
            print(f"      {k[1]} {k[2]}v{k[3]} ent={k[5]} line={k[6]} "
                  f"side={k[7]} stamp={r['stamp']}", file=out)


def _deltas(only_a, only_b):
    """Raw delta lines -> [{"direction", "rec", "raw"}, ...]."""
    return ([{"direction": "removed", "rec": json.loads(s), "raw": s}
             for s in sorted(only_a)]
            + [{"direction": "added", "rec": json.loads(s), "raw": s}
               for s in sorted(only_b)])


def _gate(only_a, only_b, waivers, today, samples, out, result=None):
    """Classify deltas against waivers; return exit code.

    Side swaps (swaps.py) are tagged before classification so only a
    ``side_swap = true`` waiver can excuse them, and printed first.
    ``result``, when given, receives the swaps and unexplained deltas
    for callers that post-process them (live_gate.py).
    """
    deltas = _deltas(only_a, only_b)
    moved = swaps.find_swaps(deltas)
    swaps.render(moved, out)
    waived, unexplained, notes = classify(deltas, waivers, today)
    if result is not None:
        result.update(swaps=moved, unexplained=unexplained)
    for wid, rows in sorted(waived.items()):
        w = next(w for w in waivers if w["id"] == wid)
        print(f"WAIVED {wid}: {len(rows)}/{w['max_rows']} rows "
              f"(expires {w['expires']})", file=out)
    for wid, n in sorted(notes["breached"].items()):
        w = next(w for w in waivers if w["id"] == wid)
        print(f"BREACHED {wid}: {n} matched > max_rows "
              f"{w['max_rows']} — none waived", file=out)
    for wid, n in sorted(notes["expired"].items()):
        w = next(w for w in waivers if w["id"] == wid)
        print(f"EXPIRED {wid} ({w['expires']}): would cover {n} "
              f"deltas — renew with a reason, or re-bless", file=out)
    if notes["stale"]:
        print(f"stale waivers (matched nothing — delete): "
              f"{', '.join(sorted(notes['stale']))}", file=out)
    if not unexplained:
        print("GATE PASS: 0 unexplained", file=out)
        return 0
    for direction in ("removed", "added"):
        rows = [d["raw"] for d in unexplained
                if d["direction"] == direction]
        if rows:
            render(f"UNEXPLAINED {direction}", rows, samples, out)
    print(f"\nGATE FAIL: {len(unexplained)} unexplained", file=out)
    return 1


def run(a_path, b_path, samples=3, out=sys.stdout,
        waivers_path=None, today=None, result=None):
    """Diff two canonical files.  Plain mode: 0 iff identical.
    Gate mode (waivers_path given): 0 iff no UNEXPLAINED delta;
    ``result`` (a dict) receives swaps + unexplained deltas."""
    if result is not None:
        result.update(swaps=[], unexplained=[])
    a, b = load(a_path), load(b_path)
    print(f"A: {len(a)} rows ({a_path})", file=out)
    print(f"B: {len(b)} rows ({b_path})", file=out)
    only_a, only_b = a - b, b - a

    if waivers_path is None:
        if not only_a and not only_b:
            print("IDENTICAL", file=out)
            return 0
        render("only in A (dropped by B)", only_a, samples, out)
        render("only in B (added by B)", only_b, samples, out)
        return 1

    today = today or datetime.date.today()
    waivers = load_waivers(waivers_path, today)
    if not only_a and not only_b:
        print("IDENTICAL", file=out)
        if waivers:
            print(f"stale waivers (matched nothing — delete): "
                  f"{', '.join(sorted(w['id'] for w in waivers))}",
                  file=out)
        print("GATE PASS: 0 unexplained", file=out)
        return 0
    return _gate(only_a, only_b, waivers, today, samples, out, result)


def main():
    p = argparse.ArgumentParser(
        description="Diff two canonical projections")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--samples", type=int, default=3,
                   help="sample rows shown per bucket (default 3)")
    p.add_argument("--waivers", default=None, metavar="FILE",
                   help="gate mode: classify deltas against this "
                        "waivers.toml; exit 0 iff no UNEXPLAINED")
    args = p.parse_args()
    try:
        sys.exit(run(args.a, args.b, samples=args.samples,
                     waivers_path=args.waivers))
    except WaiverError as e:
        print(e, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
