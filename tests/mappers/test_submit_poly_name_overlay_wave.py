"""Official Poly name-overlay wave script constants."""

from scripts.submit_poly_name_overlay_wave import NOTE, PREFIXES


def test_wave_targets_live_optic_empty_prefixes() -> None:
    assert PREFIXES == ("uru1", "lal", "ere", "fl1", "cfb")
    assert "last-token" in NOTE
    assert "Approve" not in NOTE
