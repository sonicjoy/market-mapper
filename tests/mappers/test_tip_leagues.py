"""M5: tip-driven run set and tip-only known-profile soccer configs."""

from __future__ import annotations

from pathlib import Path

from mappers.control_plane.rows import LeagueRow
from mappers.exchanges import polymarket as pm
from mappers.exchanges.dkex import league_token
from mappers.exchanges.kalshi import KalshiConfig
from mappers.run import LEAGUES
from mappers.seed.code_leagues import CODE_LEAGUES
from mappers.seed.fixture_sources import FIXTURE_SOURCE_BQ
from mappers.seed.tip_leagues import (
    api_fetch_league_keys,
    apply_tip_exchange_settings,
    league_config_from_tip_row,
    resolve_run_leagues,
)
from mappers.sport import Sport, sport_for_league


def _row(
    league: str,
    *,
    sport: str = "soccer",
    optic: str = "turkey_-_super_lig",
    horizon: float = 96.0,
    exchanges: list | None = None,
    enabled: bool = True,
    fixture_source: str = "api",
) -> LeagueRow:
    return LeagueRow(
        league=league,
        sport=sport,
        optic_league_id=optic,
        extra_optic_league_ids=[],
        fixture_source=fixture_source,
        fixture_horizon_hours=horizon,
        enabled=enabled,
        output_order=[],
        exchanges=exchanges
        or [
            {
                "sportsbook": "kalshi",
                "enabled": True,
                "parser_profile": "kalshi_generic_v1",
                "settings": {"prefix": "KXSUPERLIG", "ticker_home_first": True},
            }
        ],
        notes=None,
        tombstone=False,
    )


def test_tip_only_soccer_builds_kalshi_config() -> None:
    cfg = league_config_from_tip_row(_row("turkey_super_lig"), None)
    assert cfg is not None
    assert cfg.league == "turkey_super_lig"
    assert cfg.sport == Sport.SOCCER
    assert Path("config") / cfg.league == Path("config/turkey_super_lig")
    assert cfg.OPTIC.league_id == "turkey_-_super_lig"
    # Tip Kalshi settings play no part: the sport decides the config.
    assert KalshiConfig(sport=Sport.SOCCER) == cfg.KALSHI


def test_tip_only_super_lig_joins_config_path() -> None:
    """Prod crash: Path / TipLeague. Identity is now the BQ slug string."""
    cfg = league_config_from_tip_row(_row("super_lig"), None)
    assert cfg is not None
    assert cfg.league == "super_lig"
    assert cfg.sport == Sport.SOCCER
    assert Path("config") / cfg.league == Path("config/super_lig")


def test_tip_overlay_wins_horizon() -> None:
    epl = next(v for k, v in LEAGUES.items() if str(k) == "epl")
    row = _row(
        "epl",
        optic="england_-_premier_league",
        horizon=120.0,
        exchanges=[
            {
                "sportsbook": "kalshi",
                "enabled": True,
                "parser_profile": "kalshi_generic_v1",
                "settings": {"prefix": "KXEPL"},
            }
        ],
    )
    cfg = apply_tip_exchange_settings(epl, row)
    assert cfg.OPTIC.horizon_hours == 120.0
    assert KalshiConfig(sport=Sport.SOCCER) == cfg.KALSHI


def test_resolve_run_leagues_tip_only_default_set() -> None:
    py = {str(k): v for k, v in LEAGUES.items()}
    tip = [_row("turkey_super_lig"), _row("epl", optic="england_-_premier_league")]
    out = resolve_run_leagues(py, tip)
    assert set(out) == {"turkey_super_lig", "epl", *CODE_LEAGUES}
    assert "nba" not in out  # tip is the run set when non-empty


def test_resolve_run_leagues_filter_keys() -> None:
    py = {str(k): v for k, v in LEAGUES.items()}
    tip = [_row("turkey_super_lig"), _row("epl", optic="england_-_premier_league")]
    out = resolve_run_leagues(py, tip, filter_keys=["epl"])
    assert set(out) == {"epl"}


def test_resolve_run_leagues_falls_back_to_python_when_tip_empty() -> None:
    py = {str(k): v for k, v in LEAGUES.items()}
    out = resolve_run_leagues(py, [])
    assert "epl" in out
    assert len(out) == len(py)


def test_disabled_tip_rows_fall_back_to_python() -> None:
    """Tip present but nothing enabled → treat as empty tip (Python run set)."""
    py = {str(k): v for k, v in LEAGUES.items()}
    tip = [_row("turkey_super_lig", enabled=False)]
    out = resolve_run_leagues(py, tip)
    assert "epl" in out
    assert "turkey_super_lig" not in out
    assert len(out) == len(py)


def test_filter_keys_does_not_revive_disabled_tip_row() -> None:
    """--league must not fall back to Python when the tip disabled the slug."""
    py = {str(k): v for k, v in LEAGUES.items()}
    tip = [
        _row("epl", optic="england_-_premier_league", enabled=False),
        _row("turkey_super_lig"),
    ]
    out = resolve_run_leagues(py, tip, filter_keys=["epl", "turkey_super_lig"])
    assert set(out) == {"turkey_super_lig"}


def test_api_fetch_keys_include_tip_only_skip_bq_source() -> None:
    py = {str(k): v for k, v in LEAGUES.items()}
    tip = [
        _row("turkey_super_lig"),
        _row("epl", optic="england_-_premier_league"),
        _row("china_super_league", optic="china_-_super_league"),
        _row(
            "sweden_allsvenskan",
            optic="sweden_-_allsvenskan",
            fixture_source=FIXTURE_SOURCE_BQ,
        ),
    ]
    keys = api_fetch_league_keys(py, tip_rows=tip)
    assert "turkey_super_lig" in keys
    assert "epl" in keys
    assert "china_super_league" in keys
    assert "sweden_allsvenskan" not in keys


def test_api_fetch_keys_korea_k1_follows_tip_source() -> None:
    """Tip fixture_source=bq still skips even when the league is API-capable."""
    py = {str(k): v for k, v in LEAGUES.items()}
    keys = api_fetch_league_keys(
        py,
        tip_rows=[_row("korea_k1", optic="korea_-_k1_league", fixture_source="api")],
    )
    assert "korea_k1" in keys
    keys_bq = api_fetch_league_keys(
        py,
        tip_rows=[
            _row("korea_k1", optic="korea_-_k1_league", fixture_source=FIXTURE_SOURCE_BQ)
        ],
    )
    assert "korea_k1" not in keys_bq


def test_api_fetch_keys_skip_bq_fixture_source() -> None:
    py = {str(k): v for k, v in LEAGUES.items()}
    keys = api_fetch_league_keys(
        py,
        exclude=set(),
        tip_rows=[_row("turkey_super_lig", fixture_source=FIXTURE_SOURCE_BQ)],
    )
    assert "turkey_super_lig" not in keys


def test_tip_only_soccer_poly_gets_soccer_recognizers() -> None:
    """Path 2 tip-only leagues must parse bridge questions (not empty rules)."""
    row = _row(
        "england_championship",
        optic="england_-_championship",
        exchanges=[
            {
                "sportsbook": "optic",
                "enabled": True,
                "parser_profile": "optic_standard_v1",
                "source_league_id": "england_-_championship",
            },
            {
                "sportsbook": "polymarket",
                "enabled": True,
                "parser_profile": "poly_generic_v1",
                "source_league_id": "england_-_championship",
                "settings": {
                    "slug_prefix": "elc",
                    "optic_league_id": "england_-_championship",
                    "question_style": "mlb_suffix",
                },
            },
        ],
    )
    cfg = league_config_from_tip_row(row, None)
    assert cfg is not None
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.slug_prefix == "elc"
    assert cfg.POLYMARKET.market_types
    assert cfg.POLYMARKET.market_rules


def test_tip_overlay_enables_poly_on_python_league_with_none() -> None:
    """efl_cup shipped POLYMARKET=None; tip must attach soccer Path 2."""

    row = _row(
        "efl_cup",
        optic="england_-_efl_cup",
        exchanges=[
            {
                "sportsbook": "polymarket",
                "enabled": True,
                "parser_profile": "poly_generic_v1",
                "settings": {
                    "slug_prefix": "efl",
                    "optic_league_id": "england_-_efl_cup",
                    "question_style": "mlb_suffix",
                },
            }
        ],
    )
    cfg = apply_tip_exchange_settings(LEAGUES['efl_cup'], row)
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.slug_prefix == "efl"
    assert cfg.POLYMARKET.market_types
    assert cfg.POLYMARKET.market_rules


def test_sport_for_league_tip_only_is_soccer() -> None:
    assert sport_for_league("epl") == sport_for_league("epl")
    assert sport_for_league("turkey_super_lig") == Sport.SOCCER


def _esports_exchanges() -> list:
    return [
        {
            "sportsbook": "optic",
            "enabled": True,
            "parser_profile": "optic_standard_v1",
            "source_league_id": "kings_of_glory",
        },
        {
            "sportsbook": "polymarket",
            "enabled": True,
            "parser_profile": "poly_generic_v1",
            "settings": {
                "slug_prefix": "hok",
                "optic_league_id": "kings_of_glory",
                "question_style": "mlb_suffix",
            },
        },
    ]


def _cricket_exchanges() -> list:
    return [
        {
            "sportsbook": "optic",
            "enabled": True,
            "parser_profile": "optic_standard_v1",
            "source_league_id": "india_-_uttar_pradesh_t20_league",
        },
        {
            "sportsbook": "polymarket",
            "enabled": True,
            "parser_profile": "poly_generic_v1",
            "settings": {
                "slug_prefix": "cricupt20",
                "optic_league_id": "india_-_uttar_pradesh_t20_league",
                "question_style": "mlb_suffix",
            },
        },
    ]


def test_tip_only_esports_builds_poly_recognizers() -> None:
    row = _row(
        "honor_of_kings",
        sport="esports",
        optic="kings_of_glory",
        exchanges=_esports_exchanges(),
    )
    cfg = league_config_from_tip_row(row, None)
    assert cfg is not None
    assert cfg.sport == Sport.ESPORTS
    assert cfg.POLYMARKET is not None
    assert cfg.POLYMARKET.slug_prefix == "hok"
    parsed = pm.parse_question(
        "Honor of Kings: JLY vs Koala Game (BO5) - Honor of Kings World Championship",
        cfg.POLYMARKET,
    )
    assert parsed is not None
    assert (parsed.team_a, parsed.team_b) == ("jly", "koala game")


def test_tip_only_cricket_builds_poly_recognizers() -> None:
    row = _row(
        "india_uttar_pradesh_t20",
        sport="cricket",
        optic="india_-_uttar_pradesh_t20_league",
        exchanges=_cricket_exchanges(),
    )
    cfg = league_config_from_tip_row(row, None)
    assert cfg is not None
    assert cfg.sport == Sport.CRICKET
    assert cfg.POLYMARKET is not None
    parsed = pm.parse_question(
        "Uttar Pradesh T20: Gorakhpur Lions vs Kanpur Superstars",
        cfg.POLYMARKET,
    )
    assert parsed is not None
    assert (parsed.team_a, parsed.team_b) == (
        "gorakhpur lions",
        "kanpur superstars",
    )
    assert pm.parse_question(
        "Namibia vs Zimbabwe: Draw",
        cfg.POLYMARKET,
    ) is None


def test_resolve_run_includes_tip_only_esports() -> None:
    py = {str(k): v for k, v in LEAGUES.items()}
    row = _row(
        "honor_of_kings",
        sport="esports",
        optic="kings_of_glory",
        exchanges=_esports_exchanges(),
    )
    run = resolve_run_leagues(py, [row])
    assert "honor_of_kings" in run
    assert run["honor_of_kings"].sport == Sport.ESPORTS


def test_nhl_underdog_pin_stays_in_the_run_set() -> None:
    """Underdog on nhl must not drop the league the gap drain fetches."""
    row = _row(
        "nhl",
        sport="hockey",
        optic="nhl",
        exchanges=[
            {
                "sportsbook": "optic", "enabled": True,
                "parser_profile": "optic_standard_v1",
                "settings": {"entity_type": "team"}, "source_league_id": "nhl",
            },
            {
                "sportsbook": "kalshi", "enabled": True,
                "parser_profile": "kalshi_generic_v1",
                "settings": {"prefix": "KXNHL"}, "source_league_id": "KXNHL",
            },
            {
                "sportsbook": "underdog", "enabled": True,
                "parser_profile": "underdog_generic_v1",
                "settings": {"league": "NHL"}, "source_league_id": "NHL",
            },
        ],
    )
    run = resolve_run_leagues({}, [row], filter_keys=["nhl"])
    assert "nhl" in run
    underdog = run["nhl"].UNDERDOG
    assert underdog is not None
    assert underdog.league == "NHL"
    assert "total_goals" in underdog.market_types


def test_dkex_comes_from_code_when_the_tip_has_no_dkex_row() -> None:
    """A league in VENUE_TOKEN_BY_SLUG maps DKEX with no tip pin."""
    run = resolve_run_leagues({}, [_row("epl", optic="england_-_premier_league")])
    dkex = run["epl"].DKEX
    assert dkex is not None
    assert dkex.league == "EPL"
    assert dkex.market_types


def test_dkex_maps_npb_and_kbo_with_the_baseball_vocab_and_nwsl_with_soccer() -> None:
    run = resolve_run_leagues({}, [
        _row("npb", sport="baseball", optic="npb"),
        _row("kbo", sport="baseball", optic="kbo"),
        _row("nwsl", optic="usa_-_nwsl"),
    ])
    npb, kbo, nwsl = run["npb"].DKEX, run["kbo"].DKEX, run["nwsl"].DKEX
    assert npb is not None and kbo is not None and nwsl is not None
    assert npb.league == "NPB"
    assert ("TRUNS", "FG") in npb.market_types
    assert kbo.league == "KBO"
    assert kbo.market_types == npb.market_types
    assert nwsl.league == "NWSL"
    assert ("DWIN", "FG") in nwsl.market_types


def test_dkex_maps_colombia_saudi_and_eredivisie_with_the_soccer_vocab() -> None:
    run = resolve_run_leagues({}, [
        _row("colombia_primera_a", optic="colombia_-_primera_a"),
        _row("saudi_pro_league", optic="saudi_arabia_-_saudi_league"),
        _row("netherlands_eredivisie", optic="netherlands_-_eredivisie"),
    ])
    for slug, token in (("colombia_primera_a", "CPL"), ("saudi_pro_league", "SAPL"),
                        ("netherlands_eredivisie", "NER")):
        cfg = run[slug].DKEX
        assert cfg is not None and cfg.league == token
        assert ("DWIN", "FG") in cfg.market_types
    assert league_token("Colombia - Primera") == "CPL"
    assert league_token("Saudi Arabia - Premier") == "SAPL"
    assert league_token("Netherlands - Eredivisie") == "NER"


def test_dkex_maps_ncaab_with_the_basketball_vocab_and_nba_is_unchanged() -> None:
    run = resolve_run_leagues({}, [
        _row("ncaab", sport="basketball", optic="ncaab"),
        _row("nba", sport="basketball", optic="nba"),
    ])
    ncaab, nba = run["ncaab"].DKEX, run["nba"].DKEX
    assert ncaab is not None and nba is not None
    assert ncaab.league == "NCAAB"
    assert ncaab.market_types == nba.market_types
    assert ("MOVY", "FG") in ncaab.market_types and ("TPTS", "FG") in ncaab.market_types
    assert nba.league == "NBA"


def test_dkex_maps_atp_challenger_with_the_tennis_pass() -> None:
    run = resolve_run_leagues({}, [
        _row("atp", sport="tennis", optic="atp"),
        _row("atp_challenger", sport="tennis", optic="atp_challenger"),
    ])
    atp, challenger = run["atp"].DKEX, run["atp_challenger"].DKEX
    assert atp is not None and challenger is not None
    assert challenger.any_league
    assert challenger.market_types == atp.market_types


def _dkex_tip_row(slug: str, optic: str, token: str, *, enabled: bool = True) -> LeagueRow:
    return _row(
        slug,
        optic=optic,
        exchanges=[{
            "sportsbook": "dkex", "enabled": enabled,
            "parser_profile": "dkex_generic_v1", "settings": {"league": token},
        }],
    )


def test_dkex_tip_row_does_not_change_the_code_config() -> None:
    """A tip DKEX pin (token, enable flag) never reaches the DKEX config."""
    code = resolve_run_leagues({}, [_row("epl", optic="england_-_premier_league")])
    for row in (
        _dkex_tip_row("epl", "england_-_premier_league", "XEPL"),
        _dkex_tip_row("epl", "england_-_premier_league", "EPL", enabled=False),
    ):
        assert resolve_run_leagues({}, [row])["epl"].DKEX == code["epl"].DKEX


def test_dkex_tip_row_cannot_turn_on_a_league_code_does_not_list() -> None:
    row = _dkex_tip_row("turkey_super_lig", "turkey_-_super_lig", "TSL")
    assert resolve_run_leagues({}, [row])["turkey_super_lig"].DKEX is None


def test_dkex_stays_off_for_a_league_code_does_not_list() -> None:
    run = resolve_run_leagues({}, [_row("turkey_super_lig")])
    assert run["turkey_super_lig"].DKEX is None
