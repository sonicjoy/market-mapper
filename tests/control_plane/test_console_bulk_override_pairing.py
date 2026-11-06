"""Bulk override pairing (pure) and venue gating (mmmapper#21)."""

from __future__ import annotations

from typing import Any

import pytest

from mappers.control_plane.console_bulk_override_pairing import (
    draft_pair,
    draft_pairs,
    leg_names,
    status_counts,
)
from mappers.control_plane.console_bulk_override_venues import (
    enabled_venues,
    shaped_source_ids,
    venue_block_reason,
)


def _sel(market_id: str, selection: str, points: float = 0.0, line: str = "") -> dict[str, Any]:
    return {
        "market_id": market_id,
        "selection": selection,
        "selection_line": line,
        "points": points,
        "selection_points": 0.0,
        "grouping_key": "default",
    }


# Real Optic rows for Slovenia v Scotland (19550-29778-2026-09-26), read 2026-09-26.
_ML_3WAY = [_sel("moneyline", "Draw"), _sel("moneyline", "Scotland"), _sel("moneyline", "Slovenia")]
_DC = [
    _sel("double_chance", "Scotland Or Draw"),
    _sel("double_chance", "Scotland Or Slovenia"),
    _sel("double_chance", "Slovenia Or Draw"),
]
# Kalshi yes_sub_title per market; the ticker itself is never decoded.
_NAMES = {"SLO": "Slovenia", "SCO": "Scotland", "TIE": "Tie", "ANA": "Anaheim Ducks", "LA": "Los Angeles Kings"}


def _leg(ticker: str, side: str = "yes", **extra: Any) -> dict[str, Any]:
    name = _NAMES.get(ticker.rsplit("-", 1)[-1], "")
    return {"source_market_id": ticker, "source_selection_id": side, "name": name, **extra}


def test_three_way_yes_and_no_sides_pair_like_the_mapper() -> None:
    ev = "KXUEFANLGAME-26SEP26SLOSCO"
    legs = [_leg(f"{ev}-{code}", side) for code in ("SLO", "SCO", "TIE") for side in ("yes", "no")]
    pairs = draft_pairs(legs, _ML_3WAY, no_selections=_DC)
    got = {(p["source_market_id"][-3:], p["source_selection_id"]): p["target"]["selection"] for p in pairs}
    assert got == {
        ("SLO", "yes"): "Slovenia",
        ("SLO", "no"): "Scotland Or Draw",
        ("SCO", "yes"): "Scotland",
        ("SCO", "no"): "Slovenia Or Draw",
        ("TIE", "yes"): "Draw",
        ("TIE", "no"): "Scotland Or Slovenia",
    }
    assert status_counts(pairs)["confident"] == 6


def test_two_way_no_is_the_other_side_but_needs_review() -> None:
    ml = [_sel("moneyline", "Anaheim Ducks"), _sel("moneyline", "Los Angeles Kings")]
    legs = [_leg(f"KXNHLGAME-26SEP26ANALA-{c}", s) for c in ("ANA", "LA") for s in ("yes", "no")]
    pairs = {(p["source_market_id"][-3:], p["source_selection_id"]): p for p in draft_pairs(legs, ml)}
    assert pairs[("ANA", "yes")]["status"] == "confident"
    # A No complement shares its Optic odd with the other side's Yes: not a clash.
    assert pairs[("ANA", "no")]["status"] == "review"
    assert pairs[("ANA", "no")]["target"]["selection"] == "Los Angeles Kings"


def test_same_side_collision_drops_both_to_ambiguous() -> None:
    ml = [_sel("moneyline", "Scotland"), _sel("moneyline", "Slovenia")]
    legs = [_leg("X-SCO"), _leg("Y-SCO")]
    pairs = draft_pairs(legs, ml)
    assert [p["status"] for p in pairs] == ["ambiguous", "ambiguous"]
    assert all(p["target"] is None for p in pairs)


def test_partial_name_is_review_and_nameless_leg_is_no_match() -> None:
    ml = [_sel("moneyline", "Miami Florida"), _sel("moneyline", "Central Michigan")]
    partial = draft_pair(_leg("X-MIA", name="Miami"), ml)
    assert (partial["status"], partial["target"]["selection"]) == ("review", "Miami Florida")
    assert draft_pair(_leg("X-ZZZ"), ml)["status"] == "no_match"


def test_two_fits_are_ambiguous_with_alternatives() -> None:
    ml = [_sel("moneyline", "Miami Florida"), _sel("moneyline", "Miami Ohio")]
    pair = draft_pair(_leg("X-MIA", name="Miami"), ml)
    assert pair["status"] == "ambiguous"
    assert {a["selection"] for a in pair["alternatives"]} == {"Miami Florida", "Miami Ohio"}


def test_line_mismatch_removes_candidate() -> None:
    spread = [_sel("point_spread", "Scotland", points=-1.5), _sel("point_spread", "Scotland", points=-0.5)]
    pair = draft_pair(_leg("X-SCO", line=-0.5), spread)
    assert (pair["status"], pair["target"]["points"]) == ("confident", -0.5)


def test_no_side_without_names_falls_back_to_manual() -> None:
    pair = draft_pair(_leg("X-QQQ", "no"), _DC)
    assert pair["status"] == "review" and pair["target"] is None and len(pair["alternatives"]) == 3


def test_leg_names_are_the_venue_text_and_tie_matches_draw() -> None:
    assert leg_names({"name": "Scotland", "code": "SCO"}) == ["Scotland"]
    assert leg_names({"name": "Tie"}) == ["Tie", "Draw"]
    assert leg_names({"code": "SCO"}) == []


# ---- venue gating ----------------------------------------------------------------------------


def test_unread_and_unshaped_venues_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAPPING_BULK_OVERRIDE_VENUES", raising=False)
    assert "market_mapping" in (venue_block_reason("crypto.com") or "")
    assert "blocked" in (venue_block_reason("Polymarket (USA)") or "")
    assert "market_id" in (venue_block_reason("polymarket") or "")
    assert "not enabled" in (venue_block_reason("novig") or "")
    assert venue_block_reason("Kalshi") is None
    assert venue_block_reason("") == "sportsbook is required"


def test_env_opt_in_enables_a_venue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_BULK_OVERRIDE_VENUES", "kalshi, Novig")
    assert enabled_venues() == frozenset({"kalshi", "novig"})
    assert venue_block_reason("novig") is None


def test_shaped_source_ids_blank_unused_fields() -> None:
    assert shaped_source_ids("kalshi", " KX-1 ", "yes") == ("KX-1", "yes")
    assert shaped_source_ids("polymarket", "ignored", "tok") == ("", "tok")
