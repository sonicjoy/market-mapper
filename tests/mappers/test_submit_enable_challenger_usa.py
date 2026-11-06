"""Enable Polymarket US on ATP Challenger (shared inner atp)."""

from scripts.submit_enable_challenger_usa import _payload
from tests.control_plane.test_gap_fix import _poly_us_league


def test_payload_enables_disabled_challenger() -> None:
    chal = _poly_us_league("atp_challenger", "atp_challenger", "", enabled=False)
    pin = _payload([chal])
    assert pin is not None
    assert pin.league == "atp_challenger"
    usa = next(ex for ex in pin.exchanges if ex.sportsbook == "polymarket_usa")
    assert usa.enabled is True
    assert usa.source_league_id == "atp"
    assert usa.settings.get("slug_prefix") == "atp"
    assert "aec-atp-fajsun-alegal-2026-09-14" in " ".join(pin.evidence_refs)


def test_payload_skips_already_enabled() -> None:
    chal = _poly_us_league("atp_challenger", "atp_challenger", "atp")
    assert _payload([chal]) is None
