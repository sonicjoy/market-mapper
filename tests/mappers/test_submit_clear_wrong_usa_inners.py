"""Clear wrong polymarket_usa inners (SETKA / shared atp)."""

from mappers.control_plane.gap_fix_poly_leagues import disable_us_pin
from scripts.submit_clear_wrong_usa_inners import _payloads
from tests.control_plane.test_gap_fix import _poly_us_league


def test_disable_us_pin_clears_inner() -> None:
    row = _poly_us_league("norway_3_division", "norway_-_3_division", "setkameua")
    pin = disable_us_pin(row)
    usa = next(ex for ex in pin["exchanges"] if ex["sportsbook"] == "polymarket_usa")
    assert usa["enabled"] is False
    assert not usa.get("source_league_id")
    assert "slug_prefix" not in (usa.get("settings") or {})


def test_payloads_skips_already_clear() -> None:
    norway = _poly_us_league("norway_3_division", "norway_-_3_division", "setkameua")
    clear_challenger = _poly_us_league("atp_challenger", "atp_challenger", "")
    clear_challenger.exchanges[0]["enabled"] = False
    out = _payloads([norway, clear_challenger])
    assert [lg.league for lg in out] == ["norway_3_division"]


def test_payloads_does_not_clear_shared_atp_challenger() -> None:
    norway = _poly_us_league("norway_3_division", "norway_-_3_division", "setkameua")
    chal = _poly_us_league("atp_challenger", "atp_challenger", "atp")
    out = _payloads([norway, chal])
    assert [lg.league for lg in out] == ["norway_3_division"]
