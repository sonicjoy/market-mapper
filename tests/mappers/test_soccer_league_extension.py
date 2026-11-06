"""Wiring coverage for the soccer-league-extension task
(feat/polymarket-parity-expansion): two new soccer leagues, Argentina
Primera División (`LEAGUES['argentina_primera'].py`) and Brazil Serie A
(`LEAGUES['brazil_serie_a'].py`), both cloned from LEAGUES['mls'].py and reusing the shared soccer
matcher (`SOCCER_MARKET_TYPES` + `soccer_market_rules`) verbatim. Both were
poly-only at onboarding.

Of ~30 candidate Polymarket bridge slug prefixes probed against Optic's live
fixture/odds feed, these two are the only ones where Optic actually returned
live fixtures + odds under the soccer_market_rules market_ids — see the
module docstrings on LEAGUES['argentina_primera'].py / LEAGUES['brazil_serie_a'].py for the full
census methodology and the live-odds confirmation for each.
"""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

import pytest  # noqa: E402

from fetch.optic import SUPPORTED_LEAGUES  # noqa: E402
from fetch.tip import optic_api_key_secret  # noqa: E402
from mappers.exchanges import polymarket as pm  # noqa: E402
from mappers.market_types import MarketType  # noqa: E402
from mappers.pipeline import _match_poly_fixture  # noqa: E402
from mappers.run import LEAGUES  # noqa: E402

_NEW_SOCCER_LEAGUES = ("argentina_primera", "brazil_serie_a")

# The 19-key soccer table_types set every poly-only soccer league in this
# codebase wires (LEAGUES['mls'].py/LEAGUES['liga_mx'].py/LEAGUES['ucl'].py's shared subset — see LEAGUES['mls'].py's
# module docstring for provenance of each key).
_SOCCER_TABLE_TYPE_KEYS = {
    "moneyline", "asian_handicap", "total_goals", "team_total",
    "1st_half_moneyline", "1st_half_total_goals", "both_teams_to_score",
    "1st_half_both_teams_to_score", "player_goals",
    "2nd_half_moneyline", "first_team_to_score", "2nd_half_total_goals",
    "1st_half_team_total", "2nd_half_team_total", "player_assists",
    "player_shots", "player_shots_on_target", "player_goals_+_assists",
    "correct_score",
}


# === Registry wiring ===


@pytest.mark.parametrize("league", _NEW_SOCCER_LEAGUES)
def test_new_league_in_leagues_registry(league):
    assert league in LEAGUES


@pytest.mark.parametrize("league", _NEW_SOCCER_LEAGUES)
def test_new_league_has_no_px(league):
    assert LEAGUES[league].PX is None


def test_brazil_serie_a_crypto_wired():
    # Pre-2026-08-12 was poly-only; crypto (BRSA) now wired.
    crypto = LEAGUES["brazil_serie_a"].CRYPTO
    assert crypto is not None
    assert crypto.league == "BRSA"


@pytest.mark.parametrize("league", _NEW_SOCCER_LEAGUES)
def test_new_league_polymarket_config_present(league):
    cfg = LEAGUES[league].POLYMARKET
    assert cfg is not None
    assert cfg.market_types == pm.SOCCER_MARKET_TYPES
    assert cfg.market_rules is pm.soccer_market_rules
    assert cfg.question_style == "mlb_suffix"
    # optic_league_id on the POLYMARKET config must agree with the league's
    # own OpticConfig.league_id (single source of truth, no drift).
    assert cfg.optic_league_id == LEAGUES[league].OPTIC.league_id


@pytest.mark.parametrize("league", _NEW_SOCCER_LEAGUES)
def test_new_league_optic_table_types_has_soccer_market_ids(league):
    table_types = LEAGUES[league].OPTIC.table_types
    assert set(table_types) >= _SOCCER_TABLE_TYPE_KEYS
    # and every one resolves to a MarketType the shared soccer rules produce
    for key in _SOCCER_TABLE_TYPE_KEYS:
        assert isinstance(table_types[key], MarketType)


def test_argentina_primera_slug_and_optic_league_id():
    cfg = LEAGUES["argentina_primera"].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "arg"
    assert cfg.optic_league_id == "argentina_-_primera_division"
    assert LEAGUES["argentina_primera"].OPTIC.league_id == "argentina_-_primera_division"


def test_brazil_serie_a_slug_and_optic_league_id():
    cfg = LEAGUES["brazil_serie_a"].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "bra"
    assert cfg.optic_league_id == "brazil_-_serie_a"
    assert LEAGUES["brazil_serie_a"].OPTIC.league_id == "brazil_-_serie_a"


# === fetch/optic.py invariants ===


@pytest.mark.parametrize("league", _NEW_SOCCER_LEAGUES)
def test_new_league_has_secret_entry(league):
    assert optic_api_key_secret(str(league)) == "opticodds_access_key"


@pytest.mark.parametrize("league", _NEW_SOCCER_LEAGUES)
def test_new_league_in_supported_leagues(league):
    assert str(league) in SUPPORTED_LEAGUES


def test_supported_leagues_cover_new_soccer_leagues():
    for league in _NEW_SOCCER_LEAGUES:
        assert str(league) in SUPPORTED_LEAGUES


# === Alias-resolution tests (mirrors test_wnba_wiring.py's pattern) ===


class _FX:
    """Minimal optic-fixture stand-in carrying only what _match_poly_fixture reads."""

    def __init__(self, home_name, away_name, start_date):
        self.home_name = home_name
        self.away_name = away_name
        self.start_date = start_date


def _game_parsed(team_a_poly_name: str, team_b_poly_name: str, date: str):
    """A minimal GAME-scope ParsedMarket with poly team names pre-normalized
    the way parse_question's soccer moneyline/total rules would (mlb_suffix)."""
    return pm.ParsedMarket(
        market_type=MarketType.GAME_TOTAL,
        team_a=pm._norm_name(team_a_poly_name, "mlb_suffix"),
        team_b=pm._norm_name(team_b_poly_name, "mlb_suffix"),
        side_mode=pm.SideMode.OVER_UNDER,
        line=2.5,
        date=date,
    )


# --- Argentina Primera: 3 aliases ---


def test_argentina_primera_has_exactly_3_aliases():
    cfg = LEAGUES["argentina_primera"].POLYMARKET
    assert cfg is not None
    assert len(cfg.team_name_aliases) == 3


@pytest.mark.parametrize(
    "poly_name,optic_name",
    [
        ("CA Vélez Sarsfield", "Club Atlético Vélez Sarsfield"),
        ("CSyD Defensa y Justicia", "CSD Defensa y Justicia"),
        ("Gimnasia y Esgrima de La Plata", "Gimnasia y Esgrima La Plata"),
    ],
)
def test_argentina_primera_alias_resolves_fixture(poly_name, optic_name):
    cfg = LEAGUES["argentina_primera"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX(optic_name, "CA River Plate", "2026-07-25T23:00:00Z")]
    parsed = _game_parsed(poly_name, "CA River Plate", "2026-07-25")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_argentina_primera_alias_without_scope_does_not_match():
    # Confirms the overlay (not incidental normalization) does the work --
    # without team_alias_scope active, plain containment alone cannot bridge
    # "CA Vélez Sarsfield" / "Club Atlético Vélez Sarsfield".
    fixtures = [_FX("Club Atlético Vélez Sarsfield", "CA River Plate", "2026-07-25T23:00:00Z")]
    parsed = _game_parsed("CA Vélez Sarsfield", "CA River Plate", "2026-07-25")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


def test_argentina_primera_estudiantes_disambiguation_no_collision():
    # Regression guard for the specific ambiguity investigated in
    # LEAGUES['argentina_primera'].py's module docstring: poly's "AA Estudiantes"
    # (Río Cuarto) must resolve to ITS fixture and never to the separate
    # "Estudiantes de La Plata" fixture, even with both alive at once.
    cfg = LEAGUES["argentina_primera"].POLYMARKET
    assert cfg is not None
    rio_cuarto_fixture = _FX("AA Estudiantes de Río Cuarto", "CA Tigre", "2026-07-25T17:45:00Z")
    la_plata_fixture = _FX("Club Estudiantes de La Plata", "CA Independiente", "2026-07-26T20:15:00Z")
    fixtures = [rio_cuarto_fixture, la_plata_fixture]

    parsed_rio_cuarto = _game_parsed("AA Estudiantes", "CA Tigre", "2026-07-25")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed_rio_cuarto, fixtures, cfg.question_style)
    assert fx is rio_cuarto_fixture

    parsed_la_plata = _game_parsed("Estudiantes de La Plata", "CA Independiente", "2026-07-26")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed_la_plata, fixtures, cfg.question_style)
    assert fx is la_plata_fixture


def test_argentina_primera_alias_regression_normal_club_still_matches():
    # CA Boca Juniors <-> CA Boca Juniors: plain containment, unaffected by
    # the alias overlay being active.
    cfg = LEAGUES["argentina_primera"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("CA Boca Juniors", "CA River Plate", "2026-07-25T23:00:00Z")]
    parsed = _game_parsed("CA Boca Juniors", "CA River Plate", "2026-07-25")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_argentina_primera_alias_genuinely_absent_team_still_drops():
    cfg = LEAGUES["argentina_primera"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("CA Boca Juniors", "CA River Plate", "2026-07-25T23:00:00Z")]
    parsed = _game_parsed("CA Talleres", "CA Huracán", "2026-07-25")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is None


# --- Brazil Serie A: 4 aliases ---


def test_brazil_serie_a_has_exactly_4_aliases():
    cfg = LEAGUES["brazil_serie_a"].POLYMARKET
    assert cfg is not None
    assert len(cfg.team_name_aliases) == 4


@pytest.mark.parametrize(
    "poly_name,optic_name",
    [
        ("Associação Chapecoense de Futebol", "Chapecoense AF"),
        ("CA Mineiro", "Clube Atlético Mineiro"),
        ("CA Paranaense", "Club Athletico Paranaense"),
        ("Grêmio FBPA", "Grêmio FB Porto Alegrense"),
    ],
)
def test_brazil_serie_a_alias_resolves_fixture(poly_name, optic_name):
    cfg = LEAGUES["brazil_serie_a"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX(optic_name, "SE Palmeiras", "2026-07-25T23:00:00Z")]
    parsed = _game_parsed(poly_name, "SE Palmeiras", "2026-07-25")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_brazil_serie_a_alias_without_scope_does_not_match():
    fixtures = [_FX("Clube Atlético Mineiro", "SE Palmeiras", "2026-07-25T23:00:00Z")]
    parsed = _game_parsed("CA Mineiro", "SE Palmeiras", "2026-07-25")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


def test_brazil_serie_a_alias_regression_normal_club_still_matches():
    cfg = LEAGUES["brazil_serie_a"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("CR Flamengo", "SE Palmeiras", "2026-07-25T23:00:00Z")]
    parsed = _game_parsed("CR Flamengo", "SE Palmeiras", "2026-07-25")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is fixtures[0]


def test_brazil_serie_a_alias_genuinely_absent_team_still_drops():
    cfg = LEAGUES["brazil_serie_a"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX("CR Flamengo", "SE Palmeiras", "2026-07-25T23:00:00Z")]
    parsed = _game_parsed("Santos FC", "São Paulo FC", "2026-07-25")
    with pm.team_alias_scope(cfg.team_name_aliases):
        fx = _match_poly_fixture(parsed, fixtures, cfg.question_style)
    assert fx is None
