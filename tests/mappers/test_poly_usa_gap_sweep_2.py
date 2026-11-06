"""PolyUS leagues fbl/utr/cod/ow and Saudi club aliases (gateway names read 2026-11-05)."""

from mappers.exchanges.polymarket_usa_leagues import all_us_league_ids, us_league_ids
from mappers.vocab.poly_usa_name_aliases import optic_names_for


def test_new_league_ids_bind_to_their_optic_leagues():
    assert us_league_ids(("germany_-_frauen_bundesliga",)) == frozenset({313})
    assert us_league_ids(("utr_men",)) == us_league_ids(("utr_women",)) == frozenset({251})
    assert us_league_ids(("call_of_duty",)) == frozenset({23})
    assert us_league_ids(("overwatch",)) == frozenset({130})
    assert {313, 251, 23, 130} <= all_us_league_ids()


def test_saudi_aliases_are_exact_pairs():
    assert optic_names_for(["Al Qadisiyah Saudi Club", "Al Fayha Saudi Club"]) == [
        "Al-Qadsiah Al Khubar", "Al Fayha FC"]
    assert optic_names_for(["Al Hazem SC"]) == ["Al Hazm"]
    assert optic_names_for(["Al Nassr"]) == []
