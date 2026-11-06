"""DKEX name fits: a school written without its last word, nickname players, team-tagged players."""

from __future__ import annotations

from types import SimpleNamespace

from mappers.exchanges.dkex_names import team_side_for
from mappers.exchanges.dkex_players import PlayerPool


def _pool(*players: str) -> PlayerPool:
    odds = [SimpleNamespace(player_id=f"p{i}", selection=name) for i, name in enumerate(players)]
    return PlayerPool(SimpleNamespace(odds=odds))


def _sides(claimed: str, home_name: str, away_name: str) -> str | None:
    return team_side_for(claimed, home="H", away="A", home_name=home_name, away_name=away_name)


def test_school_written_without_its_last_word_fits_the_one_side() -> None:
    assert _sides("Sam Houston", "Liberty", "Sam Houston State") == "A"


def test_exact_school_wins_over_the_longer_one() -> None:
    assert _sides("Michigan", "Michigan", "Michigan State") == "H"


def test_prefix_that_fits_both_sides_is_no_side() -> None:
    assert _sides("Texas", "Texas Tech", "Texas State") is None


def test_nickname_resolves_to_the_given_name() -> None:
    assert _pool("Cameron Skattebo", "Josh Allen").resolve("1", "Cam Skattebo") == "cameron_skattebo"
    assert _pool("Joshua Samanski").resolve("2", "Josh Samanski") == "joshua_samanski"


def test_nickname_needs_the_same_family_name() -> None:
    assert _pool("Cameron Ward").resolve("3", "Cam Skattebo") is None


def test_team_tag_on_a_participant_is_ignored() -> None:
    assert _pool("Emmett Mosley").resolve("4", "Emmett Mosley (TEX)") == "emmett_mosley"


def test_a_multi_player_selection_is_never_a_single_player() -> None:
    assert _pool("CJ Stroud + Cameron Ward").resolve("5", "C.J. Stroud") is None


def test_acronym_club_name_fits_the_initials() -> None:
    assert team_side_for("LAFC", home="H", away="A", home_name="Los Angeles FC",
                         away_name="Vancouver Whitecaps FC", club_short=True) == "H"


def test_country_tag_on_a_club_is_ignored() -> None:
    assert team_side_for("River Plate [ARG]", home="H", away="A", home_name="CA River Plate",
                         away_name="AA Estudiantes de Rio Cuarto", club_short=True) == "H"


def test_player_spelled_differently_resolves_when_unique() -> None:
    assert _pool("Conner Antley", "Dax Smith").resolve("a", "Connor Antley") == "conner_antley"
    assert _pool("Tristan Muyumba").resolve("b", "Trystan Muyumba") == "tristan_muyumba"
    assert _pool("Magomed-Shapi Suleymanov").resolve("c", "Shapi Suleymanov") == "magomed-shapi_suleymanov"
    assert _pool("Sang-bin Jeong").resolve("d", "Jeong Sang-bin") == "sang-bin_jeong"
    assert _pool("Kevin Concepcion", "Garrett Wilson").resolve("e", "KC Concepcion") == "kevin_concepcion"
    assert _pool("Jose Artur de Lima Junior", "Max Moran").resolve("f", "Artur") == "jose_artur_de_lima_junior"


def test_player_alike_is_no_hit_when_two_fit() -> None:
    assert _pool("Jose Pinto Silva", "Jose Maria Silva").resolve("g", "Jose Silva") is None


def test_club_prefixed_listing_is_the_same_player() -> None:
    odds = [SimpleNamespace(player_id="p1", selection="Joao Klauss de Mello"),
            SimpleNamespace(player_id="p2", selection="LA Galaxy :: Joao Klauss de Mello")]
    assert PlayerPool(SimpleNamespace(odds=odds)).resolve("h", "Joao Klauss") == "joao_klauss_de_mello"


def test_nobody_scores_selection() -> None:
    odds = [SimpleNamespace(player_id=None, selection="No goal"),
            SimpleNamespace(player_id="p1", selection="Erling Haaland")]
    assert PlayerPool(SimpleNamespace(odds=odds)).resolve("i", "No Goalscorer") == "no_goal"


def test_short_given_name_inside_a_longer_optic_name() -> None:
    assert _pool("Daniel Lorenzo Guerrero").resolve("j", "Dani Lorenzo") == "daniel_lorenzo_guerrero"


def test_transliterated_name_with_no_identical_part() -> None:
    assert _pool("Yehor Yarmoliuk").resolve("k", "Yegor Yarmolyuk") == "yehor_yarmoliuk"


def test_person_with_a_second_family_name_fits() -> None:
    from mappers.exchanges.dkex_names import person_side_for
    assert person_side_for("Murkel Alejandro Dellien Velasco", home="H", away="A",
                           home_name="Thiago Seyboth Wild", away_name="Murkel Dellien") == "A"
    assert person_side_for("Elmer Moeller", home="H", away="A",
                           home_name="Zsombor Piros", away_name="Elmer Moller") is None
