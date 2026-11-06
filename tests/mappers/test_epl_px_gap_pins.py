"""PX EPL gap pins: Optic 4-char codes vs PX 3-letter abbreviations."""

from mappers.seed.fixture_store import load_fixturefrom mappers.seed.sot import entities_to_alias_datadef test_aug22_px_epl_optic_code_pins() -> None:
    """Tip entity aliases resolve PX abbreviations to Optic canonical codes."""
    snap = load_fixture()
    alias_data, _ = entities_to_alias_data(
        snap.entities, league="epl", entity_type="team",
    )
    px = alias_data.by_exchange["px"]
    assert px["IPS"] == "ITF2"
    assert px["HUL"] == "HCA7"
    assert px["MUN"] == "MUF9"
    assert px["MNU"] == "MUF9"
    assert px["SUN"] == "SAU3"
