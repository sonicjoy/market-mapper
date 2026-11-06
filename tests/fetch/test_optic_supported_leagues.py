"""Regression coverage for fetch/optic.py tip-resolved SUPPORTED_LEAGUES."""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from fetch.optic import SUPPORTED_LEAGUES, optic_config_for  # noqa: E402
from fetch.tip import optic_api_key_secret, resolved_leagues  # noqa: E402

_EXPANSION_LEAGUES = ("mls", "liga_mx", "ucl")


def test_supported_leagues_match_resolved_run_set():
    """SUPPORTED_LEAGUES tracks the tip-resolved run set with Optic."""
    expected = {
        slug: cfg.OPTIC
        for slug, cfg in resolved_leagues().items()
        if cfg.OPTIC is not None
    }
    assert SUPPORTED_LEAGUES == expected


def test_expansion_leagues_are_fetchable():
    for league in _EXPANSION_LEAGUES:
        assert league in SUPPORTED_LEAGUES

    assert SUPPORTED_LEAGUES["mls"].league_id == "usa_-_major_league_soccer"
    assert SUPPORTED_LEAGUES["liga_mx"].league_id == "mexico_-_liga_mx"
    assert SUPPORTED_LEAGUES["ucl"].league_id == "uefa_-_champions_league"


def test_expansion_leagues_have_tip_api_key_secret():
    for league in _EXPANSION_LEAGUES:
        assert optic_api_key_secret(league) == "opticodds_access_key"


def test_optic_config_for_wired_and_unknown():
    for league in _EXPANSION_LEAGUES:
        assert optic_config_for(league) is SUPPORTED_LEAGUES[league]
    assert optic_config_for("not_a_real_league") is None


def test_wnba_is_fetchable_with_tip_secret():
    assert "wnba" in SUPPORTED_LEAGUES
    assert SUPPORTED_LEAGUES["wnba"].league_id == "wnba"
    assert optic_api_key_secret("wnba") == "opticodds_access_key"
