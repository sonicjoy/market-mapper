"""Reconcile our exchange matcher with Optic passthrough source_ids.

When Optic stamps ``source_ids["Polymarket"]`` / ``Novig`` on an odd, we only
keep that id if our own matcher would attach the same token to the same
canonical row.  On disagreement we strip Optic's id (missing > wrong), log it,
and record an RFQ block so the fold cannot let Optic's ORIGINAL row win.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, field

from BigQuery.alerts import bool_env
from mappers.exchanges.optic import Odd

POLY_BOOK = "Polymarket"
NOVIG_BOOK = "Novig"
USA_BOOK = "Polymarket (USA)"

# Strip reason for the NO listing of a per-team two-outcome US symbol: our
# complement pass stamps it back, so it is logged but never alerted.
TWO_WAY_NO = "two_way_no"


@dataclass
class CrosscheckStats:
    """Per-league passthrough cross-check counts."""

    agree: int = 0
    disagree: int = 0
    ours_only: int = 0
    optic_only: int = 0
    unverified_books: int = 0


@dataclass
class CrosscheckLedger:
    """Run-wide disagreements and optic-only tokens (for alerts + fold block)."""

    disagreements: list[dict[str, str]] = field(default_factory=list)
    optic_only: list[dict[str, str]] = field(default_factory=list)
    seen_disagree: set[str] = field(default_factory=set)

    def record_disagree(
        self,
        *,
        league: str,
        sportsbook: str,
        token: str,
        our_key: str,
        optic_key: str,
        rfq_key: str,
        detail: str = "",
    ) -> None:
        fp = f"{sportsbook}|{token}"
        if fp in self.seen_disagree:
            return
        self.seen_disagree.add(fp)
        self.disagreements.append({
            "league": league,
            "sportsbook": sportsbook,
            "token": token,
            "our_row_key": our_key,
            "optic_row_key": optic_key,
            "rfq_key": rfq_key,
            "detail": detail,
        })

    def record_optic_only(
        self,
        *,
        league: str,
        sportsbook: str,
        token: str,
        optic_key: str,
    ) -> None:
        self.optic_only.append({
            "league": league,
            "sportsbook": sportsbook,
            "token": token,
            "optic_row_key": optic_key,
        })


def passthrough_token(odd: Odd | None, sportsbook: str) -> str | None:
    """Exchange-native id from Optic source_ids for one book."""
    if odd is None:
        return None
    src = (odd.source_ids or {}).get(sportsbook)
    if not isinstance(src, dict):
        return None
    val = (
        src.get("selection_id")
        if sportsbook == NOVIG_BOOK
        else src.get("selection_id") or src.get("market_id")
    )
    return str(val) if val else None


def rfq_key_from_source_ids(sportsbook: str, source_ids: Mapping | None) -> str:
    """Fold ``rfq_key``: sportsbook|market_id|selection_id (empty when absent)."""
    src = source_ids or {}
    market = str(src.get("market_id") or "")
    selection = str(src.get("selection_id") or "")
    return f"{sportsbook.lower()}|{market}|{selection}"


def odds_by_token(
    odd_lookup: Mapping[str, Odd], sportsbook: str,
) -> dict[str, list[Odd]]:
    """Every Optic odd carrying this book's passthrough token."""
    out: dict[str, list[Odd]] = {}
    for odd in odd_lookup.values():
        tok = passthrough_token(odd, sportsbook)
        if tok:
            out.setdefault(tok, []).append(odd)
    return out


def strip_passthrough(odd: Odd, sportsbook: str) -> bool:
    """Remove one book from source_ids; return True when something was removed."""
    src = odd.source_ids or {}
    if sportsbook not in src:
        return False
    odd.source_ids = {k: v for k, v in src.items() if k != sportsbook}
    return True


def _log_strip(
    league: str,
    sportsbook: str,
    token: str,
    our_key: tuple,
    optic_key: tuple,
) -> None:
    print(
        f"  {sportsbook.lower()} [{league}] passthrough crosscheck: "
        f"dropping token {token} — ours {our_key} vs optic {optic_key}",
        file=sys.stderr,
    )


def reconcile_tokens(
    *,
    league: str,
    sportsbook: str,
    matcher_index: Mapping[str, tuple],
    optic_index: Mapping[str, tuple],
    odd_lookup: Mapping[str, Odd],
    ledger: CrosscheckLedger | None,
    stats: CrosscheckStats,
) -> None:
    """Strip Optic passthrough ids that disagree with our matcher index."""
    by_token = odds_by_token(odd_lookup, sportsbook)
    optic_for_book = {tok: key for tok, key in optic_index.items() if tok in by_token}
    for token, our_key in matcher_index.items():
        optic_key = optic_for_book.get(token)
        if optic_key is None:
            stats.ours_only += 1
            continue
        if optic_key == our_key:
            stats.agree += 1
            continue
        _drop_disagreement(
            by_token.get(token, []), sportsbook, league, token,
            our_key, optic_key, ledger, stats,
        )
    for token, optic_key in optic_for_book.items():
        if token in matcher_index:
            continue
        stats.optic_only += 1
        if ledger is not None:
            ledger.record_optic_only(
                league=league,
                sportsbook=sportsbook,
                token=token,
                optic_key=str(optic_key),
            )


def _drop_disagreement(
    odds: list[Odd],
    sportsbook: str,
    league: str,
    token: str,
    our_key: tuple,
    optic_key: tuple,
    ledger: CrosscheckLedger | None,
    stats: CrosscheckStats,
) -> None:
    """Strip every odd that carries a disagreed token and record one block."""
    stats.disagree += 1
    rfq = ""
    for odd in odds:
        src = (odd.source_ids or {}).get(sportsbook)
        if not rfq and isinstance(src, dict):
            rfq = rfq_key_from_source_ids(sportsbook, src)
        strip_passthrough(odd, sportsbook)
    _log_strip(league, sportsbook, token, our_key, optic_key)
    if ledger is not None:
        ledger.record_disagree(
            league=league,
            sportsbook=sportsbook,
            token=token,
            our_key=str(our_key),
            optic_key=str(optic_key),
            rfq_key=rfq,
        )


def crosscheck_enabled() -> bool:
    return bool_env("MAPPING_OPTIC_PASSTHROUGH_CROSSCHECK", default=True)
