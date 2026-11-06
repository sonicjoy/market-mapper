"""DKEX college basketball: the ``ncaab`` slug maps under the NCAAB token.

Catalogue rows mirror the live book's shape (UCLA @ Arizona, competition
01481J0QLBLMJ28); ``subTopic`` and the ticker prefix are both "NCAAB".
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mappers.exchanges.dkex import VENUE_TOKEN_BY_SLUG, DkexConfig, league_token
from mappers.exchanges.dkex_pass import run_pass
from mappers.vocab import dkex_markets as vocab

CBB = DkexConfig(
    league="NCAAB", market_types=vocab.BASKETBALL, ignored_markets=vocab.BASKETBALL_IGNORED,
)
COMP = "01481J0QLBLMJ28"
ARIZ = {"id": "DKT_00B0O10", "name": "Arizona", "role": "home"}
UCLA = {"id": "DKT_00UCLA0", "name": "UCLA", "role": "away"}


def _row(stat: str, *, team: dict | None = None, strike: float | None = None,
         outcome: str | None = None, suffix: str = "") -> dict:
    return {
        "symbol": f"NCAAB-{stat}-FG-{COMP}-{suffix}",
        "is_combo": False, "status": "active",
        "event_start": "2026-11-03T03:00:00+00:00",
        "participant_id": team["id"] if team else None,
        "participant_name": team["name"] if team else None,
        "stat_achievement": stat, "time_period": "FG",
        "strike_price": strike, "outcome_type": outcome,
        "competition_id": COMP, "competition_name": "UCLA @ Arizona",
        "league_name": "NCAAB", "sub_topic": "NCAAB",
        "participants": [team] if team else [],
        "legs": None, "source": "api",
    }


def _catalogue() -> list[dict]:
    return [
        _row("WIN", team=UCLA, suffix="UCLA005"),
        _row("WIN", team=ARIZ, suffix="ARNA019"),
        _row("MOVY", team=ARIZ, strike=7.5, outcome="GTE", suffix="ARNA019-GTE-P00075"),
        _row("MOVY", team=UCLA, strike=7.5, outcome="GTE", suffix="UCLA005-GTE-P00075"),
        _row("TPTS", strike=150.5, outcome="GTE", suffix="GTE-P01505"),
    ]


def _stamp(tmp_path: Path, *, home: str = "ARIZ", away: str = "UCLA",
           home_name: str = "Arizona", away_name: str = "UCLA") -> list:
    (tmp_path / "dkex_markets.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in _catalogue()), encoding="utf-8",
    )
    entry = SimpleNamespace(fixture=SimpleNamespace(
        start_date="2026-11-03T03:00:00Z", home=home, away=away,
        home_name=home_name, away_name=away_name, odds=[],
    ))
    out: list = []

    def attach(_index, _alt, _all, dr) -> str:
        out.append(dr)
        return "stamped"

    run_pass("ncaab", CBB, [entry], {}, [], tmp_path, attach)
    return out


def test_ncaab_slug_carries_the_ncaab_token() -> None:
    assert VENUE_TOKEN_BY_SLUG["ncaab"] == "NCAAB"
    assert league_token("NCAAB") == "NCAAB"


def test_win_maps_to_a_moneyline_pair_per_team(tmp_path: Path) -> None:
    """A WIN row (the away team's, as listed) stamps yes on that team and no on the opponent."""
    rows = _stamp(tmp_path)
    ucla = [r for r in rows if r.dkex_symbol.endswith("UCLA005")]
    assert [(r.side, r.dkex_side, r.dkex_market) for r in ucla] == [
        ("UCLA", "yes", "WIN"), ("ARIZ", "no", "WIN"),
    ]
    arizona = [r for r in rows if r.dkex_symbol.endswith("ARNA019")]
    assert [(r.side, r.dkex_side) for r in arizona] == [("ARIZ", "yes"), ("UCLA", "no")]


def test_movy_is_the_spread_on_the_named_team(tmp_path: Path) -> None:
    """MOVY on X at strike s is X -s on the yes side, the opponent +s on the no side."""
    rows = _stamp(tmp_path)
    ariz = [r for r in rows if "MOVY" in r.dkex_symbol and "ARNA019" in r.dkex_symbol]
    assert [(r.side, r.line, r.dkex_side) for r in ariz] == [
        ("ARIZ", -7.5, "yes"), ("UCLA", 7.5, "no"),
    ]
    ucla = [r for r in rows if "MOVY" in r.dkex_symbol and "UCLA005" in r.dkex_symbol]
    assert [(r.side, r.line, r.dkex_side) for r in ucla] == [
        ("UCLA", -7.5, "yes"), ("ARIZ", 7.5, "no"),
    ]


def test_tpts_is_the_game_total(tmp_path: Path) -> None:
    rows = _stamp(tmp_path)
    tpts = [r for r in rows if r.dkex_market == "TPTS"]
    assert [(r.side, r.line, r.dkex_side) for r in tpts] == [
        ("over", 150.5, "yes"), ("under", 150.5, "no"),
    ]


def test_sides_follow_the_names_when_optic_orients_the_game_the_other_way(tmp_path: Path) -> None:
    rows = _stamp(tmp_path, home="UCLA", away="ARIZ", home_name="UCLA", away_name="Arizona")
    ariz = [r for r in rows if "MOVY" in r.dkex_symbol and "ARNA019" in r.dkex_symbol]
    assert [(r.side, r.line) for r in ariz] == [("ARIZ", -7.5), ("UCLA", 7.5)]


# === Nothing else moves ===

#: Every slug but ncaab, as it stood before ncaab was added.
OTHER_SLUGS = {
    "nfl": "NFL", "ncaaf": "CFB", "cfb": "CFB", "mlb": "MLB", "npb": "NPB", "kbo": "KBO",
    "wnba": "WNBA", "nba": "NBA", "nhl": "NHL", "ufc": "UFC", "atp": "ATP", "wta": "WTA",
    "atp_challenger": "ATPCH", "itf_men": "ITFM", "itf_women": "ITFW", "epl": "EPL",
    "england_championship": "EFLC", "efl_cup": "ELC", "la_liga": "LALIGA", "ucl": "UCL",
    "europa_league": "UEL", "europa_conference_league": "UECL", "italy_serie_a": "ISA",
    "italy_coppa_italia": "COPPAIT", "germany_bundesliga": "BUNDESLIGA",
    "france_ligue_1": "LIGUE1", "brazil_serie_a": "BSA", "argentina_primera": "LPA",
    "mls": "MLS", "nwsl": "NWSL", "liga_mx": "LIGAMX",
    "international_club_friendlies": "FRIENDLYCLUB",
    "colombia_primera_a": "CPL",
    "saudi_pro_league": "SAPL",
    "netherlands_eredivisie": "NER",
}


def test_every_other_league_keeps_its_token() -> None:
    assert {k: v for k, v in VENUE_TOKEN_BY_SLUG.items() if k != "ncaab"} == OTHER_SLUGS


@pytest.mark.parametrize(("sub_topic", "token"), [
    ("NBA", "NBA"), ("WNBA", "WNBA"), ("NCAAF", "CFB"), ("NCAA FCS", "CFB"),
    ("NBA Preseason", "NBA"), ("NCAAB", "NCAAB"),
])
def test_league_tokens_for_neighbouring_leagues_are_unchanged(sub_topic: str, token: str) -> None:
    assert league_token(sub_topic) == token
