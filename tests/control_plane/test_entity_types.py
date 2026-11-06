"""Match-side entity_type (home/away vs player props)."""

from mappers.control_plane.entity_types import match_entity_type, match_entity_type_for_row
from mappers.control_plane.entry_structured import _pin_entity_type
from mappers.control_plane.rows import LeagueRow


def test_tennis_match_sides_are_team() -> None:
    assert match_entity_type("itf_women") == "team"
    assert match_entity_type("atp", sport="tennis") == "team"
    assert match_entity_type("wta", settings_type="player") == "team"


def test_combat_is_fighter() -> None:
    assert match_entity_type("ufc") == "fighter"
    assert match_entity_type("premier_boxing") == "fighter"
    assert match_entity_type("x", sport="mma") == "fighter"


def test_boxing_empty_settings_stay_team_until_retag() -> None:
    boxing = LeagueRow(
        league="boxing_matches",
        sport="boxing",
        optic_league_id="boxing_matches",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[],
        settings={},
    )
    assert match_entity_type_for_row(boxing) == "team"


def test_row_settings_team_wins_over_name() -> None:
    row = LeagueRow(
        league="ufc",
        sport="mma",
        optic_league_id="ufc",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[],
        settings={"entity_type": "team"},
    )
    assert match_entity_type_for_row(row) == "team"


def test_structured_pin_coerces_tennis_player_to_team() -> None:
    assert _pin_entity_type(
        [], None, "itf_women", "player", None, "Teodora Vlajic",
    ) == "team"
