"""Official Polymarket Path 2 gap-wave payload construction."""

from __future__ import annotations

from mappers.control_plane.rows import LeagueRow
from mappers.seed.poly_usa_exchange import POLY_BOOK, POLY_USA_BOOK
from scripts.submit_poly_path2_gap_wave import (
    ENABLE_OFFICIAL,
    NEW_LEAGUES,
    build_leagues,
    official_prefix,
    poly_settings,
)


def _usa_only(slug: str, optic: str, inner: str) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport="soccer",
        optic_league_id=optic,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=168.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "optic",
                "enabled": True,
                "parser_profile": "optic_standard_v1",
                "source_league_id": optic,
                "settings": {},
            },
            {
                "sportsbook": POLY_USA_BOOK,
                "enabled": True,
                "parser_profile": "poly_usa_generic_v1",
                "source_league_id": inner,
                "settings": {"slug_prefix": inner},
            },
        ],
    )


def test_prefixes_are_unique() -> None:
    enable = list(ENABLE_OFFICIAL.values())
    fresh = [item[3] for item in NEW_LEAGUES]
    all_pfx = enable + fresh
    assert len(all_pfx) == len(set(all_pfx))
    slugs = list(ENABLE_OFFICIAL) + [item[0] for item in NEW_LEAGUES]
    assert len(slugs) == len(set(slugs))


def test_enable_re_enables_stub_polymarket_pin() -> None:
    row = _usa_only("caribbean_premier_league", "west_indies_-_caribbean_premier_league", "cplcr")
    row.exchanges.append(
        {
            "sportsbook": POLY_BOOK,
            "enabled": None,
            "parser_profile": "poly_generic_v1",
            "source_league_id": None,
            "settings": {},
        },
    )
    leagues = build_leagues([row])
    cpl = next(lg for lg in leagues if lg.league == "caribbean_premier_league")
    poly = next(ex for ex in cpl.exchanges if ex.sportsbook == POLY_BOOK)
    assert poly.enabled is True
    assert poly.settings["slug_prefix"] == "criccpl"


def test_enable_adds_official_poly_beside_usa() -> None:
    row = _usa_only("russia_premier_league", "russia_-_premier_league", "rpl")
    leagues = build_leagues([row])
    rus = next(lg for lg in leagues if lg.league == "russia_premier_league")
    books = {ex.sportsbook: ex for ex in rus.exchanges}
    assert books[POLY_USA_BOOK].source_league_id == "rpl"
    assert books[POLY_BOOK].settings["slug_prefix"] == "rus"
    assert rus.clone_market_rules_from is None


def test_skips_when_prefix_already_set() -> None:
    row = _usa_only("russia_premier_league", "russia_-_premier_league", "rpl")
    row.exchanges.append(
        {
            "sportsbook": POLY_BOOK,
            "enabled": True,
            "parser_profile": "poly_generic_v1",
            "source_league_id": "russia_-_premier_league",
            "settings": poly_settings("russia_-_premier_league", "rus"),
        },
    )
    leagues = build_leagues([row])
    assert all(lg.league != "russia_premier_league" for lg in leagues)


def test_new_league_onboards_optic_and_official_poly() -> None:
    leagues = build_leagues([])
    ja2 = next(lg for lg in leagues if lg.league == "japan_j2_league")
    assert ja2.clone_market_rules_from == "colombia_primera_a"
    assert official_prefix([e.model_dump(mode="json") for e in ja2.exchanges]) == "ja2"
    enabled = {ex.sportsbook for ex in ja2.exchanges if ex.enabled}
    assert enabled == {"optic", POLY_BOOK}
