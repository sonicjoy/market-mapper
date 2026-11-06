"""Ticker / player-code helpers."""

from goalscorer import codes

GOAL = "KXEPLGOAL-26AUG25ARSCHE-ARSBSAKA7-1"


def test_ticker_segments():
    assert codes.series(GOAL) == "KXEPLGOAL"
    assert codes.fixture_part(GOAL) == "26AUG25ARSCHE"
    assert codes.player_code(GOAL) == "ARSBSAKA7-1"
    assert codes.ml_team_abbrev("KXEPLGAME-26AUG25ARSCHE-ARS") == "ARS"
    assert codes.build_ticker("KXEPLGOAL", "26AUG25ARSCHE", "ARSBSAKA7-1") == GOAL


def test_goal_line_helpers():
    assert codes.is_anytime(GOAL) and codes.is_anytime("ARSBSAKA7-1")
    assert not codes.is_anytime("KXUCLGOAL-26OCT13ATMMUN-MUNBFERNA8-2")
    assert not codes.is_anytime("MUNBFERNA8-3") and not codes.is_anytime("MUNBFERNA8-11")
    assert codes.anytime_code("MUNBFERNA8-3") == codes.anytime_code("MUNBFERNA8-1") == "MUNBFERNA8-1"


def test_goal_prefix_only_from_game_series():
    assert codes.goal_prefix_for_series("KXEPLGAME") == "KXEPLGOAL"
    assert codes.goal_prefix_for_series("KXINTLFRIENDLYGAME") == "KXINTLFRIENDLYGOAL"
    assert codes.goal_prefix_for_series("KXEPLTOTAL") is None


def test_parse_code_with_known_team_length():
    assert codes.parse_code("ARSBSAKA7-1") == codes.CodeParts("ARS", "B", "SAKA", "7")
    assert codes.parse_code("MUBFERNA8-1", "MU") == codes.CodeParts("MU", "B", "FERNA", "8")
    assert codes.parse_code("ARS7-1") is None
    assert codes.parse_code("ARSB7-1") is None  # no surname fragment


def test_code_team_prefers_longest_abbreviation():
    assert codes.code_team("MUNBFERNA8-1", ["MU", "MUN"]) == "MUN"
    assert codes.code_team("CHECPALME10-1", ["ARS", "CHE"]) == "CHE"
    assert codes.code_team("LIVMSALAH11-1", ["ARS", "CHE"]) is None


def test_rank_and_suggest():
    parts = codes.parse_code("ARSBSAKA7-1")
    assert parts
    ranked = codes.rank_candidates(parts, {"Bukayo Saka", "Kai Havertz", "Bukayo Sakamoto"})
    assert ranked[0] == ("Bukayo Saka", 100)
    assert codes.suggest(ranked) == "Bukayo Saka"


def test_suggest_refuses_ties_and_weak_matches():
    assert codes.suggest([("A Smith", 90), ("A Smithers", 90)]) is None
    assert codes.suggest([("Bob Jones", 50)]) is None
    assert codes.suggest([]) is None


def test_line_code_swaps_the_goal_line():
    assert codes.line_code("ARSBSAKA7-1", "2") == "ARSBSAKA7-2"
    assert codes.line_code("MUNBFERNA8-3", "3") == "MUNBFERNA8-3"


def test_player_goals_key_matches_optic():
    # Keys as Optic publishes them on player_goals prices.
    assert codes.player_goals_key("Ryan O'Reilly", 1.5) == "ryan_o_reilly:1.5"
    assert codes.player_goals_key("A.J. Greer", 2.5) == "a_j_greer:2.5"
    assert codes.player_goals_key("Kang-In Lee", 1.5) == "kang-in_lee:1.5"
    assert codes.player_goals_key("Dávid Hancko", 1.5) == "d_vid_hancko:1.5"
    assert codes.player_goals_key("Julián Alvarez", 2.5) == "juli_n_alvarez:2.5"


def test_accents_and_letters_nfkd_misses():
    parts = codes.parse_code("ARSMODEGA8-1")
    assert parts
    assert codes.rank_candidates(parts, {"Martin Ødegaard"})[0][1] >= codes.SUGGEST_MIN_SCORE
    assert codes.normalise_name("  Martín   ØDEGAARD ") == codes.normalise_name("martin odegaard")


def test_name_particles_skipped_for_surname():
    parts = codes.parse_code("BARFJONG21-1")
    assert parts
    assert codes.score_candidate(parts.first_initial, parts.surname, "Frenkie de Jong") == 100


def test_first_goal_ticker_helpers():
    first = "KXUCLFIRSTGOAL-26OCT13GALBAR-BARLYAMAL10"
    assert codes.first_goal_prefix("KXUCLGOAL") == "KXUCLFIRSTGOAL"
    assert codes.anytime_prefix("KXUCLFIRSTGOAL") == "KXUCLGOAL" and codes.anytime_prefix("KXUCLGOAL") == "KXUCLGOAL"
    assert codes.is_first_goal(first) and not codes.is_first_goal(GOAL) and not codes.is_anytime(first)
    assert codes.to_anytime(first) == "KXUCLGOAL-26OCT13GALBAR-BARLYAMAL10-1"
    assert codes.to_anytime("KXUCLGOAL-26OCT13GALBAR-BARLYAMAL10-3") == "KXUCLGOAL-26OCT13GALBAR-BARLYAMAL10-1"
    assert codes.to_first_goal("KXUCLGOAL-26OCT13GALBAR-BARLYAMAL10-1") == first
    assert codes.to_first_goal(first) == first
