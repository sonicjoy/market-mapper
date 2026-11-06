"""Round-trip tests for mapping_league schema extensions."""

from __future__ import annotations

from mappers.control_plane.league_review import payload_as_row
from mappers.control_plane.models import ExchangePin, MappingLeaguePayload


def test_mapping_league_payload_carries_league_settings():
    payload = MappingLeaguePayload(
        league="norway_eliteserien",
        sport="soccer",
        optic_league_id="norway_-_eliteserien",
        entity_type="team",
        alias_enforcement="warn",
        runshop_enabled=False,
        exchanges=[
            ExchangePin(
                sportsbook="polymarket",
                enabled=True,
                parser_profile="poly_generic_v1",
                settings={"slug_prefix": "nor"},
            ),
            ExchangePin(
                sportsbook="polymarket_usa",
                enabled=True,
                parser_profile="poly_usa_generic_v1",
                source_league_id="nor1",
            ),
            ExchangePin(
                sportsbook="novig",
                enabled=True,
                parser_profile="novig_generic_v1",
                settings={"league": "Norway Eliteserien"},
                source_league_id="Norway Eliteserien",
            ),
        ],
    )
    row = payload_as_row(payload)
    assert row.settings == {
        "entity_type": "team",
        "alias_enforcement": "warn",
        "runshop_enabled": False,
    }
    poly = next(ex for ex in row.exchanges if ex["sportsbook"] == "polymarket")
    assert poly["settings"]["slug_prefix"] == "nor"
    poly_usa = next(ex for ex in row.exchanges if ex["sportsbook"] == "polymarket_usa")
    assert poly_usa["source_league_id"] == "nor1"
    dumped = payload.model_dump(mode="json")
    again = MappingLeaguePayload.model_validate(dumped)
    assert again.entity_type == "team"
    assert again.league_settings() == payload.league_settings()
