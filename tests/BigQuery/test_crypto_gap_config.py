"""Tests for crypto gap league config registry."""

from BigQuery.crypto_gap_config import (
    all_gap_leagues,
    distinct_gap_leagues,
    fixture_prefix_from_symbol,
    fixture_prefix_re,
    gap_league_for_cli_arg,
    gap_league_for_prefix,
    gap_league_for_symbol,
    league_keys_for_prefix,
    sql_string_list,
)


def test_all_gap_leagues_includes_mlb_and_fifa():
    prefixes = {g.league_prefix for g in all_gap_leagues()}
    assert "NX.F.OPT.FIFA" in prefixes
    assert "NX.F.OPT.MLB" in prefixes
    assert "NX.F.OPT.NBA" in prefixes
    assert "NX.F.OPT.UCL" in prefixes
    assert "NX.F.OPT.FRL1" in prefixes
    assert "NX.F.OPT.ITSA" in prefixes
    assert "NX.F.OPT.DEB" in prefixes
    assert "NX.F.OPT.CFB" in prefixes
    assert "NX.F.OPT.UFC" in prefixes
    assert "NX.F.OPT.LMX" in prefixes


def test_tennis_tours_share_tennis_prefix():
    # ATP, Challenger, ITF, and WTA share one symbol namespace. Challenger uses
    # ATP's crypto meta_league; ITF uses best-guess ITF; each has its own Optic
    # fixture set.
    by_key = {g.league_key: g for g in all_gap_leagues()}
    assert by_key["atp"].league_prefix == "NX.F.OPT.TENNIS"
    assert by_key["atp_challenger"].league_prefix == "NX.F.OPT.TENNIS"
    assert by_key["itf_men"].league_prefix == "NX.F.OPT.TENNIS"
    assert by_key["itf_women"].league_prefix == "NX.F.OPT.TENNIS"
    assert by_key["wta"].league_prefix == "NX.F.OPT.TENNIS"


def test_distinct_gap_leagues_collapses_shared_prefix():
    prefixes = [g.league_prefix for g in distinct_gap_leagues()]
    # No prefix is repeated, and tennis tours fold into a single TENNIS entry.
    assert len(prefixes) == len(set(prefixes))
    assert prefixes.count("NX.F.OPT.TENNIS") == 1
    tennis = next(g for g in distinct_gap_leagues() if g.league_prefix == "NX.F.OPT.TENNIS")
    assert "Moneyline" in tennis.game_lines
    assert tennis.optic_league_ids == frozenset({
        "atp", "atp_challenger", "itf_men", "itf_women", "wta",
    })


def test_league_keys_for_prefix_returns_all_tennis_leagues():
    assert sorted(league_keys_for_prefix("NX.F.OPT.TENNIS")) == [
        "atp",
        "atp_challenger",
        "itf_men",
        "itf_women",
        "wta",
    ]


def test_gap_league_for_tennis_symbol_resolves():
    sym = "NX.F.OPT.TENNIS-0056-260715-M.O.1.2.20261231"
    league = gap_league_for_symbol(sym)
    assert league is not None
    assert league.league_prefix == "NX.F.OPT.TENNIS"
    assert fixture_prefix_from_symbol(sym) == "NX.F.OPT.TENNIS-0056-260715"


def test_gap_league_for_prefix():
    assert gap_league_for_prefix("NX.F.OPT.UCL") is not None
    assert gap_league_for_prefix("NX.F.OPT.UNKNOWN") is None


def test_gap_league_for_cli_arg_accepts_key_or_prefix():
    by_key = gap_league_for_cli_arg("ucl")
    by_prefix = gap_league_for_cli_arg("NX.F.OPT.UCL")
    assert by_key is not None and by_prefix is not None
    assert by_key.league_prefix == by_prefix.league_prefix
    assert gap_league_for_cli_arg("not-a-league") is None


def test_sql_string_list_empty_uses_sentinel():
    assert sql_string_list(frozenset()) == "'__none__'"


def test_fixture_prefix_re_escapes_dots():
    assert fixture_prefix_re("NX.F.OPT.MLB") == r"NX\.F\.OPT\.MLB-\d+-\d{6}"
