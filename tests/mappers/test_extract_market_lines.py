"""Tests for px.extract_market_lines — especially sup_moneyline flavors."""

from mappers.exchanges.px import Market, extract_market_lines


def _sup_moneyline(name: str, sels: list[dict]) -> Market:
    return Market(
        id=1, name=name, type="sup_moneyline",
        status="active", sport_event_id=1, selections=sels,
    )


def test_sup_moneyline_yes_no_flavor():
    """DD/TD shipped as sup_moneyline with YES/NO display_names."""
    market = _sup_moneyline(
        "Napheesa Collier To Record a Double Double",
        [
            {"display_name": "YES", "line": 0, "line_id": "a",
             "name": "YES", "outcome_id": 1},
            {"display_name": "NO", "line": 0, "line_id": "b",
             "name": "NO", "outcome_id": 2},
        ],
    )
    (line,) = extract_market_lines(market)
    assert line.line is None
    assert {s.outcome_id for s in line.selections} == {1, 2}


def test_sup_moneyline_yes_no_case_insensitive():
    market = _sup_moneyline(
        "Player To Record a Triple Double",
        [
            {"display_name": "Yes", "line": 0, "line_id": "a",
             "name": "Yes", "outcome_id": 1},
            {"display_name": "no", "line": 0, "line_id": "b",
             "name": "no", "outcome_id": 2},
        ],
    )
    (line,) = extract_market_lines(market)
    assert line.line is None


def test_sup_moneyline_ou_flavor_unchanged():
    market = _sup_moneyline(
        "Player Total Points",
        [
            {"display_name": "Over 10.5", "line": 0, "line_id": "a",
             "name": "Over 10.5", "outcome_id": 1},
            {"display_name": "Under 10.5", "line": 0, "line_id": "b",
             "name": "Under 10.5", "outcome_id": 2},
        ],
    )
    (line,) = extract_market_lines(market)
    assert line.line == 10.5


def test_cftc_sup_moneyline_strike_keys():
    """CFTC vocabulary: strike_id / strike instead of line_id / line."""
    market = _sup_moneyline(
        "Player Total Points",
        [
            {"display_name": "Over 10.5", "strike": 0, "strike_id": "a",
             "name": "Over 10.5", "outcome_id": 1},
            {"display_name": "Under 10.5", "strike": 0, "strike_id": "b",
             "name": "Under 10.5", "outcome_id": 2},
        ],
    )
    (line,) = extract_market_lines(market)
    assert line.line == 10.5
    assert {s.line_id for s in line.selections} == {"a", "b"}


def test_cftc_spread_market_strikes():
    """CFTC market_strikes + strike/strike_id normalize like market_lines."""
    market = Market(
        id=1,
        name="Spread",
        type="spread",
        status="active",
        sport_event_id=1,
        market_strikes=[
            {
                "strike": -3.5,
                "selections": [
                    {
                        "display_name": "Home -3.5",
                        "strike": -3.5,
                        "strike_id": "home",
                        "name": "Home -3.5",
                        "outcome_id": 1714,
                        "competitor_id": 1,
                    },
                    {
                        "display_name": "Away +3.5",
                        "strike": 3.5,
                        "strike_id": "away",
                        "name": "Away +3.5",
                        "outcome_id": 1715,
                        "competitor_id": 2,
                    },
                ],
            },
        ],
    )
    (line,) = extract_market_lines(market)
    assert line.line == -3.5
    by_id = {s.line_id: s for s in line.selections}
    assert by_id["home"].spread_line == -3.5
    assert by_id["away"].spread_line == 3.5


def test_cftc_total_market_strikes():
    market = Market(
        id=1,
        name="Total Points",
        type="total",
        status="active",
        sport_event_id=1,
        market_strikes=[
            {
                "strike": 220.5,
                "selections": [
                    {
                        "display_name": "Over 220.5",
                        "strike": 220.5,
                        "strike_id": "over",
                        "name": "Over",
                        "outcome_id": 12,
                    },
                    {
                        "display_name": "Under 220.5",
                        "strike": 220.5,
                        "strike_id": "under",
                        "name": "Under",
                        "outcome_id": 13,
                    },
                ],
            },
        ],
    )
    (line,) = extract_market_lines(market)
    assert line.line == 220.5
    assert {s.line_id for s in line.selections} == {"over", "under"}
