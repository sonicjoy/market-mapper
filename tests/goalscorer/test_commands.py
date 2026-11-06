"""Channel message → command parsing."""

import pytest

from goalscorer.commands import Command, parse_command


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("international_-_friendlies", Command("add_league", "international_-_friendlies")),
        ("`england_-_premier_league`", Command("add_league", "england_-_premier_league")),
        ("International_-_Friendlies", Command("add_league", "international_-_friendlies")),
        (
            "international_-_friendlies kxintlfriendlygoal",
            Command("add_league", "international_-_friendlies", "KXINTLFRIENDLYGOAL"),
        ),
        ("202608110FBC008C", Command("map_fixture", "202608110FBC008C")),
        ("202608110fbc008c", Command("map_fixture", "202608110FBC008C")),
        ("19089-22537-2026-08", Command("map_fixture", "19089-22537-2026-08")),
        ("KXEPLGAME-26AUG25ARSCHE", Command("map_ticker", "KXEPLGAME-26AUG25ARSCHE")),
        ("kxeplgoal-26aug25arsche-arsbsaka7-1", Command("map_ticker", "KXEPLGOAL-26AUG25ARSCHE-ARSBSAKA7-1")),
        (
            "<https://kalshi.com/markets/kxeplgame/premier-league-game/kxeplgame-26aug25arsche|link>",
            Command("map_ticker", "KXEPLGAME-26AUG25ARSCHE"),
        ),
    ],
)
def test_commands(text, expected):
    assert parse_command(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "hello", "can someone check KXEPLGAME-26AUG25ARSCHE", "2026-09-25", "premier_league", ":+1:"],
)
def test_chatter_is_ignored(text):
    assert parse_command(text) is None
