"""Polymarket US ticker ↔ Optic fixture matcher."""

from __future__ import annotations

from mappers.control_plane.gap_fix_poly import slug_from_optic_id
from mappers.control_plane.poly_us_match import (
    best_fixture,
    question_matches_fixture,
    unique_optic_for_events,
    unique_optic_for_questions,
)
from mappers.poly_usa_code_bind import code_hits


def test_code_hits_abbr_and_name() -> None:
    assert code_hits("seo", "SEO", "FC Seoul") == 2
    assert code_hits("seo", "SUFC", "FC Seoul") == 2
    assert code_hits("zzz", "AAA", "Other Club") == 0
    assert code_hits("wash", "WASH", "Washington") == 2
    assert code_hits("washst", "WASH", "Washington") < 2


def _uw_wsu_fx() -> dict:
    return {
        "d": "2026-09-06",
        "home_abbr": "WASH",
        "home_name": "Washington",
        "home_id": "oid-uw",
        "away_abbr": "WSU",
        "away_name": "Washington State",
        "away_id": "oid-wsu",
    }


def test_best_fixture_unique_same_orientation() -> None:
    event = {"home": "seo", "away": "uls", "date": "2026-08-29"}
    fixtures = [
        {
            "d": "2026-08-29",
            "home_abbr": "SUFC",
            "home_name": "FC Seoul",
            "home_id": "oid-seo",
            "away_abbr": "UHD",
            "away_name": "Ulsan Hyundai",
            "away_id": "oid-uls",
        }
    ]
    hit = best_fixture(event, fixtures)
    assert hit is not None
    assert hit["orient"] == "same"
    assert hit["fx"]["home_id"] == "oid-seo"


def test_best_fixture_rejects_tied_top() -> None:
    event = {"home": "aaa", "away": "bbb", "date": "2026-08-29"}
    fixtures = [
        {
            "d": "2026-08-29",
            "home_abbr": "AAA",
            "home_name": "Aaa",
            "home_id": "1",
            "away_abbr": "BBB",
            "away_name": "Bbb",
            "away_id": "2",
        },
        {
            "d": "2026-08-29",
            "home_abbr": "AAA",
            "home_name": "Aaa",
            "home_id": "3",
            "away_abbr": "BBB",
            "away_name": "Bbb",
            "away_id": "4",
        },
    ]
    assert best_fixture(event, fixtures) is None


def test_best_fixture_uses_gateway_names_when_codes_miss() -> None:
    event = {
        "home": "jsinxx",
        "away": "calcar",
        "date": "2026-08-29",
        "title": "Jannik Sinner vs. Carlos Alcaraz",
        "team_names": {"jsinxx": "Jannik Sinner", "calcar": "Carlos Alcaraz"},
    }
    fixtures = [
        {
            "d": "2026-08-29",
            "optic_league_id": "itf_men",
            "home_abbr": "",
            "home_name": "Jannik Sinner",
            "home_id": "oid-sin",
            "away_abbr": "",
            "away_name": "Carlos Alcaraz",
            "away_id": "oid-alc",
        }
    ]
    hit = best_fixture(event, fixtures)
    assert hit is not None
    assert hit["orient"] == "same"
    assert hit["fx"]["home_id"] == "oid-sin"


def test_best_fixture_bind_keys_reverse_and_apostrophe() -> None:
    event = {
        "home": "llorxx",
        "away": "amchxx",
        "date": "2026-08-29",
        "title": "Lorenzo Lorusso vs. Andrea M'chich",
        "team_names": {"llorxx": "Lorenzo Lorusso", "amchxx": "Andrea M'chich"},
    }
    fixtures = [
        {
            "d": "2026-08-29",
            "optic_league_id": "itf_men",
            "home_abbr": "",
            "home_name": "Lorusso Lorenzo",
            "home_id": "oid-lor",
            "away_abbr": "",
            "away_name": "Andrea Mchich",
            "away_id": "oid-mch",
        }
    ]
    hit = best_fixture(event, fixtures)
    assert hit is not None
    assert hit["orient"] == "same"
    assert hit["fx"]["home_id"] == "oid-lor"


def test_best_fixture_washst_title_orients_flip() -> None:
    """Cougars/Huskies hide school names; title covers, leftover codes flip."""
    event = {
        "home": "washst",
        "away": "wash",
        "date": "2026-09-06",
        "title": "Washington vs Washington State",
        "team_names": {"washst": "Cougars", "wash": "Huskies"},
    }
    hit = best_fixture(event, [_uw_wsu_fx()])
    assert hit is not None
    assert hit["orient"] == "flip"
    assert hit["fx"]["home_id"] == "oid-uw"


def test_best_fixture_washst_title_order_is_not_ticker_order() -> None:
    event = {
        "home": "washst",
        "away": "wash",
        "date": "2026-09-06",
        "title": "Washington vs Washington State",
    }
    hit = best_fixture(event, [_uw_wsu_fx()])
    assert hit is not None
    assert hit["orient"] == "flip"


def test_best_fixture_washst_mascots_without_title_fail_closed() -> None:
    event = {
        "home": "washst",
        "away": "wash",
        "date": "2026-09-06",
        "team_names": {"washst": "Cougars", "wash": "Huskies"},
    }
    assert best_fixture(event, [_uw_wsu_fx()]) is None


def test_best_fixture_washst_title_order_not_used_without_wash_abbr() -> None:
    """School title is not ticker order when leftover cannot lock wash → WASH."""
    event = {
        "home": "washst",
        "away": "wash",
        "date": "2026-09-06",
        "title": "Washington vs Washington State",
        "team_names": {"washst": "Cougars", "wash": "Huskies"},
    }
    empty = {**_uw_wsu_fx(), "home_abbr": "", "away_abbr": ""}
    uw = {**_uw_wsu_fx(), "home_abbr": "UW"}
    assert best_fixture(event, [empty]) is None
    assert best_fixture(event, [uw]) is None


def test_best_fixture_rejects_shared_surname_challenger() -> None:
    event = {
        "home": "thiwil",
        "away": "frafer",
        "date": "2026-09-08",
        "title": "Thiago Seyboth Wild vs. Francesco Ferrari",
        "team_names": {
            "thiwil": "Thiago Seyboth Wild",
            "frafer": "Francesco Ferrari",
        },
    }
    fx = {
        "d": "2026-09-08",
        "optic_league_id": "atp_challenger",
        "home_abbr": "TSW",
        "home_name": "Thiago Seyboth Wild",
        "home_id": "oid-thi",
        "away_abbr": "GFIS",
        "away_name": "Gianmarco Ferrari",
        "away_id": "oid-gfi",
    }
    assert best_fixture(event, [fx]) is None


def test_best_fixture_name_fallback_rejects_two_optic_games() -> None:
    event = {
        "home": "aaaaaa",
        "away": "bbbbbb",
        "date": "2026-08-29",
        "team_names": {"aaaaaa": "Jannik Sinner", "bbbbbb": "Carlos Alcaraz"},
    }
    fx = {
        "d": "2026-08-29",
        "optic_league_id": "itf_men",
        "home_abbr": "",
        "home_name": "Jannik Sinner",
        "home_id": "1",
        "away_abbr": "",
        "away_name": "Carlos Alcaraz",
        "away_id": "2",
    }
    other = {**fx, "home_id": "3", "away_id": "4"}
    assert best_fixture(event, [fx, other]) is None


def test_unique_optic_for_events() -> None:
    event = {"home": "seo", "away": "uls", "date": "2026-08-29"}
    by_optic = {
        "korea_-_k_league_1": [
            {
                "d": "2026-08-29",
                "home_abbr": "SUFC",
                "home_name": "FC Seoul",
                "home_id": "oid-seo",
                "away_abbr": "UHD",
                "away_name": "Ulsan Hyundai",
                "away_id": "oid-uls",
            }
        ],
        "spain_-_la_liga": [
            {
                "d": "2026-08-29",
                "home_abbr": "VCFC",
                "home_name": "Valencia CF",
                "home_id": "oid-val",
                "away_abbr": "RBB",
                "away_name": "Real Betis",
                "away_id": "oid-bet",
            }
        ],
    }
    assert unique_optic_for_events([event], by_optic) == "korea_-_k_league_1"


def test_unique_optic_for_events_rejects_minority_hit() -> None:
    """One coincidental unique match among several events must not pin the inner."""
    miss = {"home": "aaa", "away": "bbb", "date": "2026-08-29"}
    hit = {"home": "seo", "away": "uls", "date": "2026-08-29"}
    by_optic = {
        "korea_-_k_league_1": [
            {
                "d": "2026-08-29",
                "home_abbr": "SUFC",
                "home_name": "FC Seoul",
                "home_id": "oid-seo",
                "away_abbr": "UHD",
                "away_name": "Ulsan Hyundai",
                "away_id": "oid-uls",
            }
        ],
    }
    assert unique_optic_for_events([miss, miss, hit], by_optic) == ""
    assert unique_optic_for_events([hit], by_optic) == "korea_-_k_league_1"


def test_unique_optic_for_events_uses_gateway_names() -> None:
    event = {
        "home": "jsinxx",
        "away": "calcar",
        "date": "2026-08-29",
        "team_names": {"jsinxx": "Jannik Sinner", "calcar": "Carlos Alcaraz"},
    }
    by_optic = {
        "itf_men": [
            {
                "d": "2026-08-29",
                "optic_league_id": "itf_men",
                "home_abbr": "",
                "home_name": "Jannik Sinner",
                "home_id": "oid-sin",
                "away_abbr": "",
                "away_name": "Carlos Alcaraz",
                "away_id": "oid-alc",
            }
        ],
        "spain_-_la_liga": [
            {
                "d": "2026-08-29",
                "home_abbr": "VCFC",
                "home_name": "Valencia CF",
                "home_id": "oid-val",
                "away_abbr": "RBB",
                "away_name": "Real Betis",
                "away_id": "oid-bet",
            }
        ],
    }
    assert unique_optic_for_events([event], by_optic) == "itf_men"


def test_league_slug_from_optic_id() -> None:
    assert slug_from_optic_id("paraguay_-_division_intermedia") == "paraguay_division_intermedia"


def test_question_matches_fixture_requires_long_names() -> None:
    fx = {"home_name": "FC", "away_name": "Ulsan Hyundai", "d": "2026-08-29"}
    assert question_matches_fixture("Talking about FC and Ulsan Hyundai", fx) is False
    assert question_matches_fixture("FC vs Ulsan Hyundai", fx) is True
    fx2 = {"home_name": "FC Seoul", "away_name": "Ulsan Hyundai", "d": "2026-08-29"}
    assert question_matches_fixture("FC Seoul vs Ulsan Hyundai", fx2) is True


def test_unique_optic_for_questions() -> None:
    events = [{"question": "FC Seoul vs Ulsan Hyundai", "date": "2026-08-29"}]
    by_optic = {
        "korea_-_k_league_1": [
            {"d": "2026-08-29", "home_name": "FC Seoul", "away_name": "Ulsan Hyundai"},
        ],
        "spain_-_la_liga": [
            {"d": "2026-08-29", "home_name": "Valencia CF", "away_name": "Real Betis"},
        ],
    }
    assert unique_optic_for_questions(events, by_optic) == "korea_-_k_league_1"


def test_unique_optic_for_questions_reverse_tennis() -> None:
    events = [{
        "question": "M15 Hurghada: Omar Kandil vs Lorenzo Lorusso",
        "date": "2026-08-29",
    }]
    by_optic = {
        "itf_men": [
            {
                "d": "2026-08-29",
                "optic_league_id": "itf_men",
                "home_name": "Lorusso Lorenzo",
                "away_name": "Kandil Omar",
            },
        ],
        "spain_-_la_liga": [
            {"d": "2026-08-29", "home_name": "Valencia CF", "away_name": "Real Betis"},
        ],
    }
    assert unique_optic_for_questions(events, by_optic) == "itf_men"


def test_unique_optic_for_questions_rejects_ambiguous() -> None:
    events = [{"question": "FC Seoul vs Ulsan Hyundai", "date": "2026-08-29"}]
    by_optic = {
        "korea_-_k_league_1": [
            {"d": "2026-08-29", "home_name": "FC Seoul", "away_name": "Ulsan Hyundai"},
        ],
        "korea_-_k_league_2": [
            {"d": "2026-08-29", "home_name": "FC Seoul", "away_name": "Ulsan Hyundai"},
        ],
    }
    assert unique_optic_for_questions(events, by_optic) == ""

