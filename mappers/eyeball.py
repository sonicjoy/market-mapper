"""Human-review display of matched markets.

Groups canonical rows into "bets" (both sides of a wager), selects
representative examples per market type, and prints them with enough
context from all three exchanges for a human to verify correctness.
"""

import hashlib
import re
from collections import defaultdict

from mappers.exchanges.optic import Odd
from mappers.market_types import MarketType, Shape
from mappers.shared import CanonicalRow

# === Bet grouping ===

# A bet groups all sides of the same wager.  For a spread at -8.5,
# that's two rows (CLE -8.5, MEM +8.5).  For a 3-way market, three.
BetKey = tuple[str, str, str, str, str | None, float | None, str | None]  # (start_date, home, away, market_type, entity, line, grouping_key)


def _bet_key(r: CanonicalRow) -> BetKey:
    """Group key for rows that belong to the same wager.

    For H2H markets entity varies per side (entity = side = player),
    so we exclude it — the grouping_key already identifies the matchup.
    """
    mt = MarketType(r.market_type)
    entity = None if mt.shape == Shape.H2H else r.entity
    return (
        r.start_date, r.home, r.away, r.market_type,
        entity,
        abs(r.line) if r.line is not None else None,
        r.grouping_key,
    )


# Short hex hash length for bet identification in --table / --pick.
# Birthday-problem threshold: P(collision) ≈ N²/(2·16^L).
# With ~15K bets/day, L=9 gives P ≈ 0.0016 — a collision every
# ~600 runs.  The collision check below catches it; bump if it
# fires regularly.
HASH_LEN = 9


def _bet_hash(key: BetKey) -> str:
    """Short hex hash identifying a bet, for --pick."""
    return hashlib.md5(repr(key).encode()).hexdigest()[:HASH_LEN]


def _coverage(rows: list[CanonicalRow]) -> str:
    """Coverage string: 'O' if Optic, 'P' if PX, 'K' if Kalshi."""
    o = any(r.optic_id for r in rows)
    p = any(r.px_line_id for r in rows)
    k = any(r.kalshi_ticker for r in rows)
    return ("O" if o else "") + ("P" if p else "") + ("K" if k else "")


def _coverage_rank(cov: str) -> int:
    """Lower is better: 3-way > 2-way > 1-way."""
    return -len(cov)


def group_bets(
    rows: list[CanonicalRow],
) -> dict[str, tuple[BetKey, list[CanonicalRow]]]:
    """Group rows into bets keyed by short hex hash.

    Returns {hash: (bet_key, rows)}.  Raises on hash collision.
    Both --table (for the bet column) and --eyeball (for review
    display) call this so the collision check runs once.
    """
    buckets: dict[BetKey, list[CanonicalRow]] = {}
    for r in rows:
        bk = _bet_key(r)
        buckets.setdefault(bk, []).append(r)

    result: dict[str, tuple[BetKey, list[CanonicalRow]]] = {}
    for bk, bet_rows in buckets.items():
        h = _bet_hash(bk)
        if h in result and result[h][0] != bk:
            raise ValueError(
                f"bet hash collision at HASH_LEN={HASH_LEN}: "
                f"{h!r} maps to both {result[h][0]} and {bk} "
                f"— increase HASH_LEN in eyeball.py")
        result[h] = (bk, bet_rows)

    return result


# === Selection ===

def _select_bets(
    bets: list[tuple[BetKey, list[CanonicalRow]]],
    n: int,
    with_orphans: bool = False,
) -> list[tuple[BetKey, list[CanonicalRow], str]]:
    """Pick up to N bets per coverage bucket.

    Groups bets by coverage string (e.g. "OPK", "OP", "K") and picks
    up to N from each bucket, preferring varied games within each.
    Buckets are emitted best-coverage-first (3-way, then 2-way, then
    1-way).  Single-exchange buckets are only included when
    with_orphans is True.
    """
    if not bets:
        return []

    # Group by coverage string.
    by_cov: dict[str, list[tuple[BetKey, list[CanonicalRow]]]] = defaultdict(list)
    for key, rows in bets:
        by_cov[_coverage(rows)].append((key, rows))

    # Process buckets best-coverage-first, deterministic within.
    # Skip single-exchange orphans unless requested.
    selected: list[tuple[BetKey, list[CanonicalRow], str]] = []
    for cov in sorted(by_cov, key=lambda c: (_coverage_rank(c), c)):
        if len(cov) == 1 and not with_orphans:
            continue
        bucket = sorted(by_cov[cov], key=lambda t: t[0])
        picked: list[tuple[BetKey, list[CanonicalRow], str]] = []
        seen_games: set[tuple[str, str, str]] = set()

        # First pass: one per game.
        for key, rows in bucket:
            if len(picked) >= n:
                break
            game = (key[0], key[1], key[2])
            if game not in seen_games:
                seen_games.add(game)
                picked.append((key, rows, cov))

        # Second pass: fill remaining from any game.
        if len(picked) < n:
            picked_keys = {p[0] for p in picked}
            for key, rows in bucket:
                if len(picked) >= n:
                    break
                if key not in picked_keys:
                    picked.append((key, rows, cov))

        selected.extend(picked)

    return selected


# === Formatting ===

def _optic_display(r: CanonicalRow, odd_lookup: dict[str, Odd]) -> str:
    """Human-readable Optic display for one side."""
    if r.optic_id is None:
        return "\u2014"
    odd = odd_lookup[r.optic_id]
    parts: list[str] = []
    if odd.name:
        parts.append(f'"{odd.name}"')
    if odd.market:
        parts.append(f"({odd.market})")
    return " ".join(parts) if parts else "\u2014"


def _px_display(r: CanonicalRow) -> str:
    """Human-readable PX display for one side."""
    if r.px_line_id is None:
        return "\u2014"
    parts: list[str] = []
    if r.px_selection_display_name:
        parts.append(f'"{r.px_selection_display_name}"')
    if r.px_market_name:
        parts.append(f"({r.px_market_name})")
    return " ".join(parts) if parts else "\u2014"


def _kalshi_display(r: CanonicalRow) -> str:
    """Human-readable Kalshi display for one side."""
    if r.kalshi_ticker is None:
        return "\u2014"
    parts: list[str] = []
    if r.kalshi_side:
        parts.append(f"{r.kalshi_side.upper():3}")
    if r.kalshi_yes_sub_title:
        parts.append(f'"{r.kalshi_yes_sub_title}"')
    if r.kalshi_title:
        parts.append(f'"{r.kalshi_title}"')
    # Abbreviate ticker: show only the suffix after the last dash.
    ticker_suffix = r.kalshi_ticker.rsplit("-", 1)[-1]
    parts.append(f"[{ticker_suffix}]")
    if r.kalshi_scope:
        parts.append(f"({r.kalshi_scope})")
    return " ".join(parts)


def _format_bet(
    key: BetKey,
    rows: list[CanonicalRow],
    cov: str,
    odd_lookup: dict[str, Odd],
    is_spread: bool,
) -> list[str]:
    """Format one bet block as lines of text."""
    date, home, away, _mt, entity, line, gk = key
    out: list[str] = [""]

    header = f"  {date}  {away} @ {home}"
    if entity:
        header += f"  [{entity}]"
    if gk:
        header += f"  gk={gk}"
    header += f"  ({cov})"
    out.append(header)

    def _side_rank(r: CanonicalRow) -> tuple:
        # Spreads: group opposite sides of the same bet together.
        # The favored team (negative line) identifies the pair,
        # then negative before positive within each pair.
        if is_spread:
            assert r.line is not None
            if r.line < 0:
                favored = r.side
            else:
                favored = r.away if r.side == r.home else r.home
            return (0, favored, r.line)
        if r.side in ("over", "yes"):
            return (0, "", 0)
        if r.side in ("under", "no"):
            return (0, "", 1)
        if r.side == "_TIE":
            return (0, "", 2)
        if r.side == r.home:
            return (0, "", 0)
        return (0, "", 1)

    for r in sorted(rows, key=_side_rank):
        line_str = f"  line=[{r.line}]" if r.line is not None else ""
        out.append(f"    side={r.side}{line_str}")
        out.append(f"      Optic:       {_optic_display(r, odd_lookup)}")
        out.append(f"      PX:          {_px_display(r)}")
        out.append(f"      Kalshi:  {_kalshi_display(r)}")

    return out


# === HTML formatting ===

_CSS = """\
body { font-family: system-ui, sans-serif; max-width: 960px; margin: 2em auto; }
h2 { margin-top: 2em; border-bottom: 2px solid #333; padding-bottom: 0.3em; }
.meta { color: #666; font-size: 0.9em; }
table { border-collapse: collapse; margin: 1em 0 1.5em 0; width: 100%; }
th { background: #f0f0f0; text-align: left; padding: 4px 8px;
     border: 1px solid #ccc; font-size: 0.85em; }
td { padding: 4px 8px; border: 1px solid #ccc; font-size: 0.85em; }
tr:nth-child(even) { background: #fafafa; }
caption { text-align: left; font-weight: bold; padding: 4px 0;
          font-size: 0.9em; }
.em { color: #999; }
.k-yes { background: #b7e1cd; }
.k-no { background: #f4c7c3; }
.over { background: #b3d9f2; }
.under { background: #f5e6a3; }
"""


def _html_esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _html_bet(
    key: BetKey,
    rows: list[CanonicalRow],
    cov: str,
    odd_lookup: dict[str, Odd],
    is_spread: bool,
) -> str:
    """Render one bet as an HTML table."""
    date, home, away, _mt, entity, line, gk = key

    caption = f"{date} &nbsp; {_html_esc(away)} @ {_html_esc(home)}"
    if entity:
        caption += f" &nbsp; [{_html_esc(entity)}]"
    if gk:
        caption += f" &nbsp; gk={_html_esc(gk)}"
    caption += f" &nbsp; <span class='meta'>({cov})</span>"

    lines = [
        "<table>",
        f"<caption>{caption}</caption>",
        "<tr><th>Side</th><th>Line</th>"
        "<th>Optic Name</th><th>PX Name</th>"
        "<th>K Subtitle</th><th>K Ticker</th><th>K Side</th>"
        "<th>Optic Mkt</th><th>PX Mkt</th><th>K Type</th></tr>",
    ]

    # Reuse the same sort from _format_bet.
    def _side_rank(r: CanonicalRow) -> tuple:
        if is_spread:
            assert r.line is not None
            if r.line < 0:
                favored = r.side
            else:
                favored = r.away if r.side == r.home else r.home
            return (0, favored, r.line)
        if r.side in ("over", "yes"):
            return (0, "", 0)
        if r.side in ("under", "no"):
            return (0, "", 1)
        if r.side == "_TIE":
            return (0, "", 2)
        if r.side == r.home:
            return (0, "", 0)
        return (0, "", 1)

    em = "<td></td>"

    def _cell(text: str | None) -> str:
        if not text:
            return em
        return f"<td>{_html_esc(text)}</td>"

    _over_re = re.compile(r'\bover\b', re.IGNORECASE)
    _under_re = re.compile(r'\bunder\b', re.IGNORECASE)

    def _colored_cell(text: str | None) -> str:
        """Cell with yes/no and over/under coloring."""
        if not text:
            return em
        upper = text.upper()
        if upper == "YES":
            return f"<td class='k-yes'>{_html_esc(text)}</td>"
        if upper == "NO":
            return f"<td class='k-no'>{_html_esc(text)}</td>"
        if not is_spread:
            if _over_re.search(text):
                return f"<td class='over'>{_html_esc(text)}</td>"
            if _under_re.search(text):
                return f"<td class='under'>{_html_esc(text)}</td>"
        return f"<td>{_html_esc(text)}</td>"

    for r in sorted(rows, key=_side_rank):
        line_str = str(r.line) if r.line is not None else ""

        # Optic: name and market from the odd lookup.
        if r.optic_id is not None:
            odd = odd_lookup[r.optic_id]
            optic_name, optic_mkt = odd.name, odd.market
        else:
            optic_name, optic_mkt = None, None

        # Kalshi: abbreviate ticker to suffix after last dash.
        k_ticker = (r.kalshi_ticker.rsplit("-", 1)[-1]
                    if r.kalshi_ticker else None)
        k_side = (r.kalshi_side.upper()
                  if r.kalshi_side else None)
        if r.kalshi_ticker is not None:
            assert r.kalshi_yes_sub_title, (
                f"{r.kalshi_ticker}: expected yes_sub_title")
        k_title = r.kalshi_yes_sub_title

        lines.append(
            f"<tr>{_colored_cell(r.side)}<td>{line_str}</td>"
            f"{_colored_cell(optic_name)}{_colored_cell(r.px_selection_display_name)}"
            f"{_colored_cell(k_title)}{_cell(k_ticker)}"
            f"{_colored_cell(k_side)}"
            f"{_cell(optic_mkt)}{_cell(r.px_market_name)}"
            f"{_cell(r.kalshi_scope)}</tr>"
        )

    lines.append("</table>")
    return "\n".join(lines)


# === Entry point ===

def print_review(
    rows: list[CanonicalRow],
    odd_lookup: dict[str, Odd],
    output_orders: list[tuple[MarketType, ...]],
    n: int = 1,
    picks: set[str] | None = None,
    with_orphans: bool = False,
) -> None:
    """Print the eyeball review to stdout.

    When picks is provided, only the bets matching those hashes are
    shown (from --pick).  Otherwise, _select_bets chooses N examples.
    """

    bets = group_bets(rows)
    if picks is not None:
        unknown = picks - bets.keys()
        if unknown:
            raise SystemExit(
                f"unknown bet hash(es): {', '.join(sorted(unknown))}")

    # Build a deduplicated ordered list of market types across leagues.
    seen: set[str] = set()
    ordered_types: list[MarketType] = []
    for order in output_orders:
        for mt in order:
            if mt.value not in seen:
                seen.add(mt.value)
                ordered_types.append(mt)

    # Index bets by market_type, filtering by picks when given.
    bets_by_type: dict[str, list[tuple[BetKey, list[CanonicalRow]]]] = defaultdict(list)
    for h, (bk, bet_rows) in bets.items():
        if picks is not None and h not in picks:
            continue
        bets_by_type[bk[3]].append((bk, bet_rows))

    # Print review.
    for mt in ordered_types:
        type_bets = bets_by_type.get(mt.value, [])
        if picks is not None and not type_bets:
            continue
        is_spread = mt.shape == Shape.SPREAD

        header = f"=== {mt.value} ({mt.scope.value} \u00b7 {mt.shape.value})"
        if picks is None:
            three_way = sum(1 for _, rs in type_bets if len(_coverage(rs)) == 3)
            two_way = sum(1 for _, rs in type_bets if len(_coverage(rs)) == 2)
            header += f" \u2014 {len(type_bets)} market outcomes"
            if three_way:
                header += f", {three_way} three-exchange"
            if two_way:
                header += f", {two_way} two-exchange"
        header += " ==="
        print(header)

        if picks is not None:
            selected = [(bk, rs, _coverage(rs)) for bk, rs in type_bets]
        else:
            selected = _select_bets(type_bets, n, with_orphans)
        if not selected:
            if type_bets and not with_orphans:
                print("  (only single-exchange orphans)")
            else:
                print("  (no market outcomes)")
        else:
            selected.sort(key=lambda t: t[0])
            for key, bet_rows, cov in selected:
                for line in _format_bet(
                        key, bet_rows, cov, odd_lookup, is_spread):
                    print(line)
        print()


def render_html(
    rows: list[CanonicalRow],
    odd_lookup: dict[str, Odd],
    output_orders: list[tuple[MarketType, ...]],
    n: int = 1,
    with_orphans: bool = False,
) -> str:
    """Render the eyeball review as a self-contained HTML string."""

    bets = group_bets(rows)

    # Build a deduplicated ordered list of market types across leagues.
    seen: set[str] = set()
    ordered_types: list[MarketType] = []
    for order in output_orders:
        for mt in order:
            if mt.value not in seen:
                seen.add(mt.value)
                ordered_types.append(mt)

    # Index bets by market_type.
    bets_by_type: dict[str, list[tuple[BetKey, list[CanonicalRow]]]] = defaultdict(list)
    for _h, (bk, bet_rows) in bets.items():
        bets_by_type[bk[3]].append((bk, bet_rows))

    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<title>Eyeball Review</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
        "<h1>Eyeball Review</h1>",
    ]

    for mt in ordered_types:
        type_bets = bets_by_type.get(mt.value, [])
        is_spread = mt.shape == Shape.SPREAD

        three_way = sum(1 for _, rs in type_bets if len(_coverage(rs)) == 3)
        two_way = sum(1 for _, rs in type_bets if len(_coverage(rs)) == 2)
        heading = (f"{_html_esc(mt.value)} "
                   f"({_html_esc(mt.scope.value)} \u00b7 "
                   f"{_html_esc(mt.shape.value)})")
        meta = f"{len(type_bets)} market outcomes"
        if three_way:
            meta += f", {three_way} three-exchange"
        if two_way:
            meta += f", {two_way} two-exchange"
        parts.append(f"<h2>{heading} <span class='meta'>\u2014 {meta}</span></h2>")

        selected = _select_bets(type_bets, n, with_orphans)
        if not selected:
            if type_bets and not with_orphans:
                parts.append("<p class='meta'>(only single-exchange orphans)</p>")
            else:
                parts.append("<p class='meta'>(no market outcomes)</p>")
        else:
            selected.sort(key=lambda t: t[0])
            for key, bet_rows, cov in selected:
                parts.append(_html_bet(key, bet_rows, cov, odd_lookup, is_spread))

    parts.append("</body></html>")
    return "\n".join(parts)
