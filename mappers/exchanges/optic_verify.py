"""Post-merge Optic agreement checks.

Principle: missing mapping > wrong mapping.  When Optic and an exchange
disagree on a field we can verify, strip that sportsbook stamp (or drop
the row for side corruption).  Never load a proven-wrong mapping.

Extends the PX/Kalshi source_id checks in ``optic.verify_source_ids`` with
crypto.com SecurityID verify and team-side / line checks against the Optic
odd the row claims to be.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, field

from mappers.exchanges import crypto_optic
from mappers.exchanges.optic import CRYPTO_COM_SPORTSBOOK, Odd, verify_source_ids
from mappers.market_types import MarketType, Shape
from mappers.shared import CanonicalRow, normalize_line

_TEAM_SIDE_SHAPES = frozenset({
    Shape.MONEYLINE,
    Shape.SPREAD,
    Shape.THREE_WAY,
    Shape.CORRECT_SCORE,
})


def _row_key(r: CanonicalRow) -> tuple:
    """Same merge key as pipeline.row_key (avoid circular import)."""
    return (
        r.league,
        r.start_date, r.home, r.away, r.market_type,
        r.entity, normalize_line(r.line), r.side,
        r.grouping_key,
    )


@dataclass
class VerifyStats:
    """Counts from verify_against_optic (missing > wrong strips)."""

    side_dropped: int = 0
    line_stripped: int = 0
    crypto_stripped: int = 0
    px_stripped: int = 0
    kalshi_stripped: int = 0
    dropped_optic_ids: list[str] = field(default_factory=list)


def clear_px(row: CanonicalRow) -> None:
    """Remove Prophet X stamps from a canonical row."""
    row.px_event_id = None
    row.px_line_id = None
    row.px_market_name = None
    row.px_selection_display_name = None


def clear_kalshi(row: CanonicalRow) -> None:
    """Remove Kalshi stamps from a canonical row."""
    row.kalshi_ticker = None
    row.kalshi_scope = None
    row.kalshi_title = None
    row.kalshi_yes_sub_title = None
    row.kalshi_side = None


def clear_crypto(row: CanonicalRow) -> None:
    """Remove crypto.com stamps from a canonical row."""
    row.crypto_security_id = None
    row.crypto_symbol = None
    row.crypto_market_id = None
    row.crypto_outcome_id = None
    row.crypto_selection_name = None
    row.crypto_source_ts = None


def clear_polymarket(row: CanonicalRow) -> None:
    """Remove Polymarket stamps from a canonical row."""
    row.polymarket_clob_token_id = None
    row.polymarket_condition_id = None
    row.polymarket_position_id = None
    row.polymarket_slug = None
    row.polymarket_question = None


def clear_polymarket_usa(row: CanonicalRow) -> None:
    """Remove Polymarket US ticker stamps from a canonical row."""
    row.polymarket_usa_market_id = None
    row.polymarket_usa_side = None


def clear_all_exchange_stamps(row: CanonicalRow) -> None:
    """Strip every non-Optic sportsbook stamp (row may still carry optic_id)."""
    clear_px(row)
    clear_kalshi(row)
    clear_crypto(row)
    clear_polymarket(row)
    clear_polymarket_usa(row)
    row.runshop_tx_odds_fixture_id = None
    row.runshop_market_id = None


def verify_against_optic(
    row_index: dict[tuple, CanonicalRow],
    all_rows: list[CanonicalRow],
    odd_lookup: dict[str, Odd],
    *,
    team_maps: Mapping[str, Mapping[str, str]],
    crypto_catalogue: dict[str, crypto_optic.CatalogueEntry] | None,
    kalshi_tickers: frozenset[str] | None,
) -> VerifyStats:
    """Strip exchange stamps that disagree with Optic; drop side-corrupt rows.

    ``team_maps`` keys are optic odd ids → fixture team_map (optic team_id →
    abbrev).  Rows whose side disagrees with Optic's team are removed from
    ``all_rows`` / ``row_index`` entirely so they cannot load.
    """
    stats = VerifyStats()
    _strip_side_line_mismatches(
        row_index, all_rows, odd_lookup, team_maps, stats,
    )
    if crypto_catalogue is not None:
        _strip_crypto_mismatches(
            all_rows, odd_lookup, crypto_catalogue, stats,
        )
    if kalshi_tickers is not None:
        stripped = verify_source_ids(
            row_index, odd_lookup,
            kalshi_tickers=kalshi_tickers,
            on_mismatch="strip",
        )
        stats.px_stripped += stripped.get("px_stripped", 0)
        stats.kalshi_stripped += stripped.get("kalshi_stripped", 0)
    _log_verify_stats(stats)
    return stats


def _strip_side_line_mismatches(
    row_index: dict[tuple, CanonicalRow],
    all_rows: list[CanonicalRow],
    odd_lookup: dict[str, Odd],
    team_maps: Mapping[str, Mapping[str, str]],
    stats: VerifyStats,
) -> None:
    """Drop side-corrupt rows; strip stamps on line mismatch."""
    drop_keys: list[tuple] = []
    for key, row in list(row_index.items()):
        if row.optic_id is None:
            continue
        odd = odd_lookup.get(row.optic_id)
        if odd is None:
            continue
        team_map = team_maps.get(row.optic_id)
        if _side_disagrees(row, odd, team_map):
            print(
                f"  verify: {row.optic_id}: side mismatch — Optic team "
                f"≠ row.side={row.side!r}; dropping row "
                f"(missing > wrong)",
                file=sys.stderr,
            )
            stats.side_dropped += 1
            stats.dropped_optic_ids.append(row.optic_id)
            drop_keys.append(key)
            continue
        if _line_disagrees(row, odd):
            print(
                f"  verify: {row.optic_id}: line mismatch — Optic "
                f"points={odd.points!r} row.line={row.line!r}; "
                f"stripping exchange stamps (missing > wrong)",
                file=sys.stderr,
            )
            clear_all_exchange_stamps(row)
            stats.line_stripped += 1
    for key in drop_keys:
        row_index.pop(key, None)
    if drop_keys:
        drop_set = set(drop_keys)
        all_rows[:] = [r for r in all_rows if _row_key(r) not in drop_set]


def _strip_crypto_mismatches(
    all_rows: list[CanonicalRow],
    odd_lookup: dict[str, Odd],
    catalogue: dict[str, crypto_optic.CatalogueEntry],
    stats: VerifyStats,
) -> None:
    """Strip crypto stamps whose SecurityID ≠ Optic-decoded market_id."""
    for row in all_rows:
        if not _crypto_disagrees(row, odd_lookup, catalogue):
            continue
        print(
            f"  verify: {row.optic_id}: crypto SecurityID "
            f"{row.crypto_security_id!r} ≠ Optic-decoded "
            f"crypto.com id; stripping crypto (missing > wrong)",
            file=sys.stderr,
        )
        clear_crypto(row)
        stats.crypto_stripped += 1


def _side_disagrees(
    row: CanonicalRow,
    odd: Odd,
    team_map: Mapping[str, str] | None,
) -> bool:
    """True when Optic team_id resolves to a different abbrev than row.side."""
    try:
        mt = MarketType(row.market_type)
    except ValueError:
        return False
    if mt.shape not in _TEAM_SIDE_SHAPES:
        return False
    if odd.team_id is None:
        # Draw / tie legs — side should be _TIE; not a home/away swap case.
        return False
    if not team_map or odd.team_id not in team_map:
        return False
    return team_map[odd.team_id] != row.side


def _line_disagrees(row: CanonicalRow, odd: Odd) -> bool:
    """True when both sides carry a line and they differ after normalize.

    Correct-score packs a synthetic float into row.line that is not Optic
    ``points`` — skip that shape.
    """
    try:
        mt = MarketType(row.market_type)
    except ValueError:
        return False
    if mt.shape == Shape.CORRECT_SCORE:
        return False
    if row.line is None or odd.points is None:
        return False
    return normalize_line(row.line) != normalize_line(odd.points)


def _crypto_disagrees(
    row: CanonicalRow,
    odd_lookup: dict[str, Odd],
    catalogue: dict[str, crypto_optic.CatalogueEntry],
) -> bool:
    """True when Optic crypto.com market_id decodes to a different SecurityID."""
    if row.optic_id is None or row.crypto_security_id is None:
        return False
    odd = odd_lookup.get(row.optic_id)
    if odd is None:
        return False
    src = (odd.source_ids or {}).get(CRYPTO_COM_SPORTSBOOK) or {}
    market_id = src.get("market_id") if isinstance(src, dict) else None
    if not market_id:
        return False
    decoded = crypto_optic.decode_market_id(market_id, catalogue)
    if decoded is None:
        return False
    return decoded.security_id != row.crypto_security_id


def optic_decoded_security_id(
    row: CanonicalRow,
    odd_lookup: dict[str, Odd],
    catalogue: dict[str, crypto_optic.CatalogueEntry],
) -> str | None:
    """SecurityID Optic's crypto.com source implies for this row, if unique."""
    if row.optic_id is None:
        return None
    odd = odd_lookup.get(row.optic_id)
    if odd is None:
        return None
    src = (odd.source_ids or {}).get(CRYPTO_COM_SPORTSBOOK) or {}
    market_id = src.get("market_id") if isinstance(src, dict) else None
    if not market_id:
        return None
    decoded = crypto_optic.decode_market_id(market_id, catalogue)
    return None if decoded is None else decoded.security_id


def _log_verify_stats(stats: VerifyStats) -> None:
    parts = []
    if stats.side_dropped:
        parts.append(f"{stats.side_dropped} side-dropped")
    if stats.line_stripped:
        parts.append(f"{stats.line_stripped} line-stripped")
    if stats.crypto_stripped:
        parts.append(f"{stats.crypto_stripped} crypto-stripped")
    if stats.px_stripped:
        parts.append(f"{stats.px_stripped} px-stripped")
    if stats.kalshi_stripped:
        parts.append(f"{stats.kalshi_stripped} kalshi-stripped")
    if parts:
        print(
            "  verify: optic agreement — stripped/dropped: "
            + ", ".join(parts)
            + " (missing > wrong)",
            file=sys.stderr,
        )
