"""Find side swaps among gate deltas: one contract moved to the other side.

A plain set-diff reports the 2026-09-29 flip as "26 removed, 20 added"
crypto.com moneyline rows — true, but it reads like churn.  What actually
happened is that each contract kept its bet and changed SIDE: the stamp
removed from ``side=CMO8`` is the stamp added on ``side=ENR5`` of the
same fixture and market.  That shape is the most expensive mapping
error there is (we price the opponent), so it gets its own class:

- a swap delta is tagged ``swap=True`` and the pair is reported first;
- an ordinary waiver never matches a swap delta — only a waiver carrying
  ``side_swap = true`` in its match can excuse one (``waivers.matches``);
- the live gate additionally treats a swap whose candidate side passes
  the name invariant, while the baseline side failed it, as a
  CORRECTION (the fix for a flip is itself a swap).

Canonical line shape (``project.py``): ``k`` = [league, start_date, home,
away, market_type, entity, line, side, grouping_key]; the side is k[7].
For a spread the line moves with the side (-1.5 <-> +1.5), so the line
is compared by magnitude.
"""

from __future__ import annotations

from collections import defaultdict

SIDE, LINE = 7, 6


def _bet_without_side(rec: dict) -> tuple:
    k = list(rec["k"])
    line = k[LINE]
    k[LINE] = abs(line) if isinstance(line, (int, float)) else line
    k[SIDE] = None
    parent = rec.get("parent") or {}
    return (tuple(map(str, k)), rec["sb"], str(parent.get("fixture_id")))


def _stamp_id(rec: dict) -> str:
    return repr(sorted((rec.get("stamp") or {}).items()))


def find_swaps(deltas: list[dict]) -> list[dict]:
    """Tag swap deltas in place; return one summary per moved contract.

    ``deltas`` are ``{"direction", "rec", "raw"}`` (diff._deltas).  A
    contract is swapped when it is removed from one side and added on a
    different side of the same bet (same fixture, market, |line|).
    """
    removed = defaultdict(list)
    for d in deltas:
        if d["direction"] == "removed":
            removed[(_bet_without_side(d["rec"]), _stamp_id(d["rec"]))].append(d)
    swaps = []
    for d in deltas:
        if d["direction"] != "added":
            continue
        rec = d["rec"]
        for r in removed.get((_bet_without_side(rec), _stamp_id(rec)), ()):
            if r["rec"]["k"][SIDE] == rec["k"][SIDE]:
                continue
            d["swap"] = r["swap"] = True
            swaps.append(
                {
                    "sportsbook": rec["sb"],
                    "league": rec["k"][0],
                    "fixture_id": (rec.get("parent") or {}).get("fixture_id"),
                    "market_type": rec["k"][4],
                    "stamp": rec.get("stamp"),
                    "from_side": r["rec"]["k"][SIDE],
                    "to_side": rec["k"][SIDE],
                }
            )
    return swaps


def render(swaps: list[dict], out, limit: int = 25) -> None:
    """Print the swap block of a gate report."""
    if not swaps:
        return
    print(
        f"\n== SIDE SWAPS: {len(swaps)} contracts moved to the opposite side (never waived by an ordinary waiver) ==",
        file=out,
    )
    for s in swaps[:limit]:
        print(
            f"  [{s['sportsbook']}] {s['league']} {s['fixture_id']} "
            f"{s['market_type']}: {s['stamp']}\n"
            f"      was side={s['from_side']}  now side={s['to_side']}",
            file=out,
        )
    if len(swaps) > limit:
        print(f"  ... {len(swaps) - limit} more", file=out)
