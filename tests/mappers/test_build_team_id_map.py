"""Tests for px.build_team_id_map — the modulo bijection check."""

import pytest
from mappers.exchanges.px import Competitor, Market, build_team_id_map


def _comp(id: int, abbr: str) -> Competitor:
    return Competitor(id=id, abbreviation=abbr, name=abbr, side="home")


def _market(id: int, name: str = "X: Team Total Points") -> Market:
    return Market(
        id=id, name=name, type="total",
        status="active", sport_event_id=1)


class TestBuildTeamIdMap:
    """Happy paths."""

    def test_two_markets_two_competitors(self):
        comps = [_comp(20_000_100, "MIL"), _comp(20_000_200, "CLE")]
        etm = {"MIL": "MIL", "CLE": "CLE"}
        markets = [_market(55_000_100), _market(55_000_200)]
        result = build_team_id_map(comps, markets, etm, event_id=1)
        assert result == {55_000_100: "MIL", 55_000_200: "CLE"}

    def test_one_market_one_competitor(self):
        """Events with a single competitor (e.g. futures) are fine."""
        comps = [_comp(20_000_100, "MIL")]
        etm = {"MIL": "MIL"}
        markets = [_market(55_000_100)]
        result = build_team_id_map(comps, markets, etm, event_id=1)
        assert result == {55_000_100: "MIL"}

    def test_no_team_markets(self):
        comps = [_comp(20_000_100, "MIL"), _comp(20_000_200, "CLE")]
        etm = {"MIL": "MIL", "CLE": "CLE"}
        result = build_team_id_map(comps, [], etm, event_id=1)
        assert result == {}

    def test_canonical_comes_from_event_team_map(self):
        """The etm resolves abbreviation→canonical (e.g. GS→GSW)."""
        comps = [_comp(20_000_100, "GS"), _comp(20_000_200, "CLE")]
        etm = {"GS": "GSW", "CLE": "CLE"}
        markets = [_market(55_000_100), _market(55_000_200)]
        result = build_team_id_map(comps, markets, etm, event_id=1)
        assert result == {55_000_100: "GSW", 55_000_200: "CLE"}

    def test_solo_team_total(self):
        """PX sometimes publishes only one team total; must not reject."""
        comps = [_comp(20_000_100, "MIL"), _comp(20_000_200, "CLE")]
        etm = {"MIL": "MIL", "CLE": "CLE"}
        markets = [_market(55_000_100)]  # only MIL, CLE missing
        result = build_team_id_map(comps, markets, etm, event_id=5)
        assert result == {55_000_100: "MIL"}


class TestBuildTeamIdMapErrors:
    """Injection violation errors."""

    def test_more_than_two_team_markets(self):
        comps = [_comp(20_000_100, "A"), _comp(20_000_200, "B")]
        etm = {"A": "A", "B": "B"}
        markets = [_market(1_000_100), _market(2_000_200), _market(3_000_300)]
        with pytest.raises(ValueError, match="at most 2"):
            build_team_id_map(comps, markets, etm, event_id=99)

    def test_suffix_not_in_competitors(self):
        comps = [_comp(20_000_100, "MIL"), _comp(20_000_200, "CLE")]
        etm = {"MIL": "MIL", "CLE": "CLE"}
        markets = [_market(55_000_999)]  # suffix 999 matches nobody
        with pytest.raises(ValueError, match="doesn't match any"):
            build_team_id_map(comps, markets, etm, event_id=42)

    def test_duplicate_suffix(self):
        comps = [_comp(20_000_100, "MIL"), _comp(20_000_200, "CLE")]
        etm = {"MIL": "MIL", "CLE": "CLE"}
        # Both markets have the same suffix (100)
        markets = [_market(55_000_100), _market(66_000_100)]
        with pytest.raises(ValueError, match="Duplicate team total suffix"):
            build_team_id_map(comps, markets, etm, event_id=7)

    def test_competitor_suffix_collision(self):
        """Two competitors with the same id % 1M — data integrity error."""
        comps = [_comp(20_000_100, "MIL"), _comp(21_000_100, "CLE")]
        etm = {"MIL": "MIL", "CLE": "CLE"}
        with pytest.raises(ValueError, match="competitor suffix collision"):
            build_team_id_map(comps, [], etm, event_id=9)

