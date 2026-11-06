"""Polymarket US: EFL Cup league id and the pinned Turkish club names.

Team shapes copied from live ``gateway.polymarket.us`` events and Optic
fixtures (2026-10-26), abbreviations included: the venue codes miss Optic's
(``gal`` / ``GS``), so these bind on the pinned name or not at all.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import mappers.pipeline  # noqa: F401 - settles the vocab/polymarket import cycle
from mappers.exchanges import polymarket_usa_structured as pus
from mappers.exchanges.polymarket_usa_leagues import us_league_ids

_NO_ALIASES = pus.TeamAliases(usa={}, kalshi={})
_KICKOFF = "2026-10-26T16:00:00Z"


def test_efl_cup_reads_its_gateway_league() -> None:
    assert us_league_ids(("england_-_efl_cup",)) == frozenset({190})


def _event(home: tuple[str, str], away: tuple[str, str]) -> pus.UsMarket:
    obj = {
        "league_id": 195, "event_id": "e1", "event_ticker": "evt", "event_start": _KICKOFF,
        "sportradar_game_id": "", "market_id": "m1", "slug": "m1",
        "sports_market_type": "soccer_team_full_time_winner", "line": None, "metadata": {},
        "sides": [], "teams": [{"id": "h", "abbreviation": home[0], "name": home[1]},
                               {"id": "a", "abbreviation": away[0], "name": away[1]}],
    }
    market = pus.parse_market(json.loads(json.dumps(obj)))
    assert market is not None
    return market


def _fx(home: tuple[str, str], away: tuple[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        fixture_id="F", home=home[0], away=away[0], home_name=home[1], away_name=away[1],
        home_optic_abbr=home[0], away_optic_abbr=away[0], start_date=_KICKOFF, sportradar_id=None,
    )


@pytest.mark.parametrize("gw_home,gw_away,optic_home,optic_away", [
    (("bes", "Beşiktaş JK"), ("iba", "Rams Başakşehir FK"),
     ("BJK", "Beşiktaş Jimnastik Kulübü"), ("İBA", "Medipol İstanbul Başakşehir Futbol Kulübü")),
    (("gal", "Galatasaray SK"), ("fen", "Fenerbahçe SK"),
     ("GS", "Galatasaray Spor Kulübü"), ("FB", "Fenerbahçe Spor Kulübü")),
    (("kon", "Konyaspor"), ("gen", "Gençlerbirliği SK"),
     ("KON", "Konyaspor Kulübü"), ("GNÇ", "Gençlerbirliği Spor Kulübü")),
    (("gz", "Göztepe SK"), ("or", "Çorum FK"), ("GÖZ", "Göztepe Spor Kulübü"), ("ÇFK", "Çorum FK")),
    (("gfk", "Gaziantep FK"), ("erz", "Erzurumspor FK"),
     ("GAZ", "Gaziantep Futbol Kulübü"), ("ERZ", "Erzurumspor Futbol Kulübü")),
    (("ey", "Eyüpspor"), ("kas", "Kasımpaşa SK"), ("EYÜ", "Eyüp Spor Kulübü"), ("KAS", "Kasımpaşa Spor Kulübü")),
    (("bur", "Bursaspor"), ("bas", "Bandirmaspor"),
     ("BUR", "Bursaspor Kulübü Derneği"), ("BAN", "Bandırma Spor Kulübü")),
    (("man", "Manisa Futbol Kulubu"), ("bat", "Batman Petrolspor"),
     ("MAN", "Manisa Futbol Kulübü"), ("PET", "Batman Petrol Spor Kulübü")),
    (("kar", "Fatih Karagumruk Istanbul"), ("pen", "Pendikspor"),
     ("FAT", "Fatih Karagümrük Spor Kulübü"), ("PEN", "Pendik Spor Kulübü")),
    (("bod", "Bodrum FK"), ("umr", "Umraniyespor"), ("BOD", "Bodrum FK"), ("ÜMR", "Ümraniye Spor Kulübü")),
])
def test_pinned_turkish_clubs_bind_their_fixture(gw_home, gw_away, optic_home, optic_away) -> None:
    bind, via = pus.bind_event(_event(gw_home, gw_away), [_fx(optic_home, optic_away)], _NO_ALIASES, set())
    assert via == "teams_kickoff" and bind is not None
    assert bind.team_sides == {"h": optic_home[0], "a": optic_away[0]}


def test_unpinned_spelling_of_a_pinned_club_stays_unbound() -> None:
    """Exact pairs only: the sponsor-less "Başakşehir FK" is not the pinned name."""
    m = _event(("bes", "Beşiktaş JK"), ("iba", "Başakşehir FK"))
    fx = _fx(("BJK", "Beşiktaş Jimnastik Kulübü"), ("İBA", "Medipol İstanbul Başakşehir Futbol Kulübü"))
    assert pus.bind_event(m, [fx], _NO_ALIASES, set())[0] is None
