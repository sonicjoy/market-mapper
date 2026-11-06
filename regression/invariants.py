"""Mapping invariants: rules every published mapping must obey.

The A/B diff (``diff.py``) answers "did this change move anything?" and
is blind to mappings that were ALWAYS wrong, and to a tick that never
witnessed the broken case.  These rules judge one engine output on its
own, against the tick's raw venue catalogues, so a wrong mapping fails
whether or not any baseline shares it.

Rules (each yields violations; ``FAIL`` ones gate):

``venue_label_swapped``  FAIL
    The name the venue prints on the contract (crypto.com PARTICIPANT /
    eventName, Kalshi ``yes_sub_title``, ProphetX selection) fits the
    OPPONENT of the Optic selection it was mapped to, and not the
    selection itself.  This is the 2026-09-29 incident: crypto.com
    ``UFC-00009-261003-M.O.1.1`` ("Court McGee to win") mapped to
    Optic "Eric Nolan".
``optic_disagrees``  FAIL
    Optic itself carries the same venue contract (its ``source_ids``) on
    a DIFFERENT selection of the same fixture and market.
``contract_reused``  FAIL
    One venue contract is stamped on two different sides or fixtures in
    one tick.  A contract prices one outcome.
``label_unverified``  INFO
    A side-bearing contract whose label fits neither side (or both):
    no evidence either way.  Counted so coverage is visible, never
    gated — feeds disagree on spelling all the time.

Gating is baseline-relative by default: a violation fails only when the
baseline (the SHA live on prod) does not have it too.  Violations the
baseline already has are printed as ALREADY IN PROD — they are live
losses to fix, but blocking an unrelated deploy (possibly the fix) on
them helps nobody.  ``--strict`` fails on every violation.

This module must not import from mappers/ (README design rules); see
``names.py`` for why the matching is a second transcription.

Usage:
    python -m regression.invariants CAND.json TICK_DIR [--baseline BASE.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

from regression.names import side_verdict

# key.side values that are not a competitor (totals, props, draws).
NON_COMPETITOR_SIDES = frozenset({"over", "under", "yes", "no", "_TIE", None})
# market types whose side names a competitor.
COMPETITOR_MARKETS = ("moneyline", "spread", "three_way", "to_advance", "draw_no_bet", "handicap")

FAIL, INFO = "FAIL", "INFO"


@dataclass(frozen=True)
class Violation:
    """One broken rule on one published contract."""

    rule: str
    severity: str
    sportsbook: str
    contract: str
    league: str
    fixture_id: str
    market: str
    side: str
    detail: str

    def ident(self) -> tuple[str, str, str, str]:
        """Identity across engine versions (detail text may differ)."""
        return (self.rule, self.sportsbook, self.contract, self.side)


# ---- venue catalogues (raw tick files, not the engine's copy) ----------


def _read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


@dataclass
class Catalogues:
    """Venue labels keyed by the contract id the engine stamps."""

    crypto: dict[str, str]  # Symbol -> participant label
    kalshi: dict[str, str]  # ticker -> yes_sub_title
    optic_books: dict[tuple, str]  # (fixture, market, book, id) -> selection

    @classmethod
    def load(cls, tick: Path) -> Catalogues:
        """Index one tick directory's raw venue files."""
        crypto = {}
        for r in _read_jsonl(tick / "crypto_com_markets.jsonl"):
            sym = r.get("Symbol")
            label = r.get("eventMetaPARTICIPANT") or r.get("eventName") or r.get("SecurityDesc")
            if sym and label:
                crypto[sym] = label
        kalshi = {}
        for r in _read_jsonl(tick / "kalshi_markets.jsonl"):
            if r.get("ticker"):
                kalshi[r["ticker"]] = r.get("yes_sub_title") or r.get("title") or ""
        books: dict[tuple, str] = {}
        for fx in _read_jsonl(tick / "optic_fixtures_odds.jsonl"):
            for odd in fx.get("odds") or []:
                for book, src in (odd.get("source_ids") or {}).items():
                    cid = _optic_book_id(book, src)
                    if cid:
                        books[(fx.get("id"), odd.get("market_id"), book, cid)] = odd.get("selection") or ""
        return cls(crypto=crypto, kalshi=kalshi, optic_books=books)


def _optic_book_id(book: str, src) -> str | None:
    """The contract id Optic's source_ids carries for a venue we stamp."""
    if not isinstance(src, dict):
        return None
    if book == "Kalshi" and src.get("market_id"):
        return f"{src['market_id']}:{src.get('selection_id') or 'yes'}"
    if book == "Prophet X" and src.get("selection_id"):
        return str(src["selection_id"])
    return None


# ---- engine output ------------------------------------------------------


def load_records(path: Path) -> list[dict]:
    """Engine ``mappers.run --json`` output; published rows only."""
    out = []
    for rec in _read_jsonl(path):
        if rec.get("optic_odds") is not None:  # loader: no Optic, no rows
            out.append(rec)
    return out


def _stamps(rec: dict) -> Iterator[tuple[str, str, str | None, str | None]]:
    """(sportsbook, contract id, venue label source, optic book name)."""
    if rec.get("kalshi"):
        k = rec["kalshi"]
        yield ("kalshi", f"{k.get('market_ticker')}:{k.get('side') or 'yes'}", k.get("market_ticker"), "Kalshi")
    if rec.get("prophet_x"):
        p = rec["prophet_x"]
        yield ("prophet_x", str(p.get("line_id")), None, "Prophet X")
    if rec.get("crypto_com"):
        c = rec["crypto_com"]
        yield ("crypto_com", str(c.get("symbol") or c.get("security_id")), c.get("symbol"), None)
    if rec.get("underdog"):
        u = rec["underdog"]
        yield ("underdog", f"{u.get('market_id')}:{u.get('selection_id')}", None, None)
    if rec.get("stx"):
        x = rec["stx"]
        yield ("stx", f"{x.get('market_id')}:{x.get('selection_id')}", None, None)
    if rec.get("sxbet"):
        s = rec["sxbet"]
        yield ("sx_bet", str(s.get("selection_id")), None, None)


#: Books with no venue label read here: checked for contract_reused only.
REUSE_ONLY = frozenset({"underdog", "sx_bet", "stx"})


def _competitor_names(records: Iterable[dict]) -> dict[str, dict[str, str]]:
    """fixture_id -> {side code: Optic selection name}."""
    names: dict[str, dict[str, str]] = defaultdict(dict)
    for rec in records:
        key, odd = rec["key"], rec["optic_odds"]
        side = key.get("side")
        if side in NON_COMPETITOR_SIDES or key.get("entity"):
            continue
        if key.get("market_type") not in COMPETITOR_MARKETS:
            continue
        sel = odd.get("selection")
        fx = odd.get("fixture_id")
        if sel and fx and side not in names[fx]:
            names[fx][side] = sel
    return names


def _label(sb: str, rec: dict, ref: str | None, cats: Catalogues) -> str | None:
    if sb == "crypto_com":
        return cats.crypto.get(ref or "") or rec["crypto_com"].get("selection_name")
    if sb == "kalshi":
        return cats.kalshi.get(ref or "") or (rec.get("check") or {}).get("kalshi_title")
    if sb == "prophet_x":
        return (rec.get("check") or {}).get("px_selection")
    return None


def _is_competitor(key: dict) -> bool:
    """True when the bet's side names a competitor (not over/yes/draw)."""
    return (
        key.get("side") not in NON_COMPETITOR_SIDES
        and not key.get("entity")
        and key.get("market_type") in COMPETITOR_MARKETS
    )


def _check_stamp(
    rec: dict, sb: str, cid: str, ref: str | None, book: str | None, cats: Catalogues, names: dict[str, dict[str, str]]
) -> list[Violation]:
    """The per-contract rules (optic_disagrees, the label verdicts)."""
    key, odd = rec["key"], rec["optic_odds"]
    fx, side = str(odd.get("fixture_id")), key.get("side")

    def v(rule, sev, detail):
        return Violation(rule, sev, sb, cid, str(key.get("league")), fx, str(key.get("market_type")), str(side), detail)

    out = []
    if book:
        theirs = cats.optic_books.get((fx, odd.get("market_id"), book, cid))
        if theirs is not None and theirs != odd.get("selection"):
            out.append(
                v("optic_disagrees", FAIL, f"we map it to {odd.get('selection')!r}, Optic carries it on {theirs!r}")
            )
    if not _is_competitor(key):
        return out
    own = odd.get("selection")
    opp_code = key.get("away") if side == key.get("home") else key.get("home")
    opp = names.get(fx, {}).get(opp_code)
    label = _label(sb, rec, ref, cats)
    if sb == "kalshi" and cid.endswith(":no"):
        own, opp = opp, own  # a No on X is a bet on X's opponent
    verdict = side_verdict(label, own, opp)
    if verdict == "swapped":
        out.append(
            v("venue_label_swapped", FAIL, f"venue says {label!r}; mapped to {own!r}, which is the opponent of {opp!r}")
        )
    elif verdict == "unclear":
        out.append(v("label_unverified", INFO, f"venue says {label!r}; sides {own!r} / {opp!r}"))
    return out


def _reused(used: dict[tuple[str, str], set[tuple]]) -> list[Violation]:
    """contract_reused: one venue contract on more than one bet."""
    out = []
    for (sb, cid), targets in used.items():
        if len(targets) > 1:
            ordered = sorted(targets, key=str)
            fx, market, side, *_ = ordered[0]
            out.append(
                Violation(
                    "contract_reused",
                    FAIL,
                    sb,
                    cid,
                    "",
                    str(fx),
                    str(market),
                    str(side),
                    f"stamped on {len(targets)} bets: "
                    + "; ".join(f"{t[0]} {t[1]} side={t[2]} line={t[3]}" for t in ordered[:4]),
                )
            )
    return out


def check(records: list[dict], cats: Catalogues) -> list[Violation]:
    """Every violation in one engine output."""
    out: list[Violation] = []
    names = _competitor_names(records)
    used: dict[tuple[str, str], set[tuple]] = defaultdict(set)
    for rec in records:
        key = rec["key"]
        bet = (
            str(rec["optic_odds"].get("fixture_id")),
            str(key.get("market_type")),
            key.get("side"),
            key.get("line"),
            key.get("entity"),
            key.get("grouping_key"),
        )
        for sb, cid, ref, book in _stamps(rec):
            used[(sb, cid)].add(bet)
            if sb not in REUSE_ONLY:
                out.extend(_check_stamp(rec, sb, cid, ref, book, cats, names))
    return out + _reused(used)


# ---- gating ------------------------------------------------------------


@dataclass
class Verdict:
    """Invariant outcome for one tick."""

    new: list[Violation]
    existing: list[Violation]
    fixed: list[Violation]
    info: int

    @property
    def failed(self) -> bool:
        return bool(self.new)


def compare(cand: list[Violation], base: list[Violation] | None, strict: bool = False) -> Verdict:
    """Split candidate FAILs into new / already-in-baseline."""
    fails = [x for x in cand if x.severity == FAIL]
    info = sum(1 for x in cand if x.severity == INFO)
    if base is None or strict:
        return Verdict(new=fails, existing=[], fixed=[], info=info)
    base_ids = {x.ident() for x in base if x.severity == FAIL}
    cand_ids = {x.ident() for x in fails}
    return Verdict(
        new=[x for x in fails if x.ident() not in base_ids],
        existing=[x for x in fails if x.ident() in base_ids],
        fixed=[x for x in base if x.severity == FAIL and x.ident() not in cand_ids],
        info=info,
    )


def render(verdict: Verdict, out=None, limit: int = 25) -> None:
    """Human report; the gate's reason for failing is always printed."""
    out = out or sys.stdout

    def rows(title, items):
        print(f"\n== {title}: {len(items)} ==", file=out)
        by_rule = defaultdict(list)
        for x in items:
            by_rule[x.rule].append(x)
        for rule, xs in sorted(by_rule.items()):
            print(f"  {rule}: {len(xs)}", file=out)
            for x in xs[:limit]:
                print(
                    f"    [{x.sportsbook}] {x.league} {x.fixture_id} "
                    f"{x.market} side={x.side} {x.contract}\n"
                    f"        {x.detail}",
                    file=out,
                )

    rows("NEW VIOLATIONS (gate fails)", verdict.new)
    if verdict.existing:
        rows("ALREADY IN PROD (live now, not caused by this change)", verdict.existing)
    if verdict.fixed:
        rows("FIXED by this change", verdict.fixed)
    print(f"\nunverified labels (info, not gated): {verdict.info}", file=out)


def dump(violations: list[Violation], path: Path) -> None:
    """Write violations as JSONL (CI artifact)."""
    with open(path, "w") as f:
        for x in violations:
            f.write(json.dumps(asdict(x), sort_keys=True) + "\n")


def load_violations(path: Path) -> list[Violation]:
    """Read back what ``dump`` wrote (the gate's per-run CI jobs hand violations to its verdict job)."""
    return [Violation(**d) for d in _read_jsonl(path)]


def main(argv: list[str] | None = None) -> int:
    """CLI: check a candidate output, optionally against a baseline."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("candidate", type=Path, help="mappers.run --json output")
    ap.add_argument("tick", type=Path, help="the tick directory it ran on")
    ap.add_argument("--baseline", type=Path, default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    cats = Catalogues.load(args.tick)
    cand = check(load_records(args.candidate), cats)
    base = check(load_records(args.baseline), cats) if args.baseline else None
    verdict = compare(cand, base, strict=args.strict)
    render(verdict)
    print("INVARIANTS FAIL" if verdict.failed else "INVARIANTS PASS")
    return 1 if verdict.failed else 0


if __name__ == "__main__":
    sys.exit(main())
