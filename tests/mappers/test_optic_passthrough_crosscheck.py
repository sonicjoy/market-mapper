"""Optic passthrough is stripped when our matcher disagrees."""

from __future__ import annotations

from mappers.exchanges.optic import Odd
from mappers.exchanges.optic_passthrough_crosscheck import (
    NOVIG_BOOK,
    POLY_BOOK,
    CrosscheckLedger,
    CrosscheckStats,
    reconcile_tokens,
    rfq_key_from_source_ids,
    strip_passthrough,
)


def _row_key_tuple() -> tuple:
    return ("china_league_one", "2026-09-29T11:00:00Z", "JIA", "NGB",
            "1st_half_both_teams_to_score", None, None, "no", "")


def _other_key() -> tuple:
    return ("china_league_one", "2026-09-29T11:00:00Z", "WUX", "NGB",
            "1st_half_both_teams_to_score", None, None, "no", "")


def _odd(oid: str, clob: str) -> Odd:
    return Odd(
        id=oid,
        market_id="1st_half_both_teams_to_score",
        selection="No",
        grouping_key="default",
        source_ids={"Polymarket": {"selection_id": clob}},
    )


def test_reconcile_strips_disagreeing_poly_passthrough():
    clob = "clob-china-btts"
    odd = _odd("23840-10288-2026-09-29:1st_half_both_teams_to_score:no", clob)
    odds = {odd.id: odd}
    ledger = CrosscheckLedger()
    stats = CrosscheckStats()
    reconcile_tokens(
        league="china_league_one",
        sportsbook=POLY_BOOK,
        matcher_index={clob: _other_key()},
        optic_index={clob: _row_key_tuple()},
        odd_lookup=odds,
        ledger=ledger,
        stats=stats,
    )
    assert "Polymarket" not in odd.source_ids
    assert stats.disagree == 1
    assert ledger.disagreements[0]["rfq_key"] == f"polymarket||{clob}"


def test_reconcile_keeps_agreeing_poly_passthrough():
    clob = "clob-agree"
    key = _row_key_tuple()
    odd = _odd("g:market:sel", clob)
    odds = {odd.id: odd}
    stats = CrosscheckStats()
    reconcile_tokens(
        league="china_league_one",
        sportsbook=POLY_BOOK,
        matcher_index={clob: key},
        optic_index={clob: key},
        odd_lookup=odds,
        ledger=None,
        stats=stats,
    )
    assert "Polymarket" in odd.source_ids
    assert stats.agree == 1


def test_reconcile_strips_every_odd_and_uses_novig_market_id():
    token = "outcome-1"
    src = {"event_id": "e", "market_id": "mkt", "selection_id": token}
    odd_a = Odd(
        id="a", market_id="moneyline", selection="Home", grouping_key="default",
        source_ids={NOVIG_BOOK: dict(src)},
    )
    odd_b = Odd(
        id="b", market_id="moneyline", selection="Home", grouping_key="default",
        source_ids={NOVIG_BOOK: dict(src), "Kalshi": {"market_id": "K"}},
    )
    ledger = CrosscheckLedger()
    stats = CrosscheckStats()
    ours = ("lg", "t", "H", "A", "moneyline", None, None, "H", "")
    optic = ("lg", "t", "H", "A", "moneyline", None, None, "A", "")
    reconcile_tokens(
        league="lg",
        sportsbook=NOVIG_BOOK,
        matcher_index={token: ours},
        optic_index={token: optic},
        odd_lookup={odd_a.id: odd_a, odd_b.id: odd_b},
        ledger=ledger,
        stats=stats,
    )
    assert NOVIG_BOOK not in odd_a.source_ids
    assert NOVIG_BOOK not in odd_b.source_ids
    assert odd_b.source_ids == {"Kalshi": {"market_id": "K"}}
    assert ledger.disagreements[0]["rfq_key"] == "novig|mkt|outcome-1"
    assert rfq_key_from_source_ids("Polymarket (USA)", {"market_id": "aec-nba"}) == (
        "polymarket (usa)|aec-nba|"
    )


def test_strip_passthrough_is_noop_when_absent():
    odd = Odd(id="x", market_id="m", selection="s", grouping_key="default")
    assert strip_passthrough(odd, POLY_BOOK) is False
