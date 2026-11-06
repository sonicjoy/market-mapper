"""Polymarket wiring for Leagues Cup + UEFA Europa / Europa Conference League.

These three competitions were the largest MAPPING_FAILED buckets in the
2026-08-06 prod audit (~82k / ~114k / ~150k RFQs over a 4h window) and mapped
nothing, because Optic does not carry Polymarket as a sportsbook for them —
so the `OPTIC_MAPPED_SPORTSBOOKS` passthrough emits no poly rows and name
matching is the only route. Each pairing below was verified against live prod
data before being written; these tests pin the parts that can silently rot:
the slug_prefix -> optic league_id pairing, and the alias tables' invariants.

The real-data evidence lives in the league modules' docstrings.
"""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

import pytest  # noqa: E402

from mappers.exchanges import polymarket as pm  # noqa: E402
from mappers.market_types import MarketType  # noqa: E402
from mappers.pipeline import _match_poly_fixture  # noqa: E402
from mappers.run import LEAGUES  # noqa: E402
from mappers.seed.sot import entities_to_alias_data, load_snapshot  # noqa: E402
from mappers.vocab.uefa_aliases import (  # noqa: E402
    _DISAMBIGUATE_PAIRS,
    _PAIRS,
    UEFA_TEAM_NAME_ALIASES,
)


def _poly_name_aliases(slug: str) -> dict[str, str]:
    """Polymarket name aliases from the config, else the activated tip."""
    cfg = LEAGUES[slug].POLYMARKET
    if cfg is not None and cfg.team_name_aliases:
        raw = dict(cfg.team_name_aliases)
    else:
        alias_data, _ = entities_to_alias_data(
            load_snapshot().entities, league=slug, entity_type="team",
        )
        raw = dict(alias_data.by_exchange.get("polymarket", {}))
    return {key: value for key, value in raw.items() if isinstance(value, str)}


class _FX:
    """Minimal optic-fixture stand-in carrying only what _match_poly_fixture reads."""

    def __init__(self, home_name, away_name, start_date):
        self.home_name = home_name
        self.away_name = away_name
        self.start_date = start_date


def _parsed(team_a_poly_name: str, team_b_poly_name: str, date: str):
    return pm.ParsedMarket(
        market_type=MarketType.MONEYLINE_3WAY,
        team_a=pm._norm_name(team_a_poly_name, "mlb_suffix"),
        team_b=pm._norm_name(team_b_poly_name, "mlb_suffix"),
        side_mode=pm.SideMode.THREE_WAY_FIXED,
        date=date,
    )


# (League, poly slug prefix, optic league_id) — the pairing is the thing that
# must never be guessed: a wrong optic_league_id stamps poly tokens onto another
# competition's fixtures, which is the mis-map this repo exists to prevent.
_PAIRINGS = [
    ("leagues_cup", "lec", "north_america_-_leagues_cup"),
    ("europa_league", "uel", "uefa_-_europa_league"),
    ("europa_conference_league", "col", "uefa_-_europa_conference_league"),
    ("ucl", "ucl", "uefa_-_champions_league"),
]


@pytest.mark.parametrize("league,prefix,optic_id", _PAIRINGS, ids=lambda v: str(v))
def test_polymarket_pairing_is_wired(league, prefix, optic_id):
    cfg = LEAGUES[league].POLYMARKET
    assert cfg is not None, f"{league} has no PolymarketConfig"
    assert cfg.slug_prefix == prefix
    assert cfg.optic_league_id == optic_id
    # The poly config must agree with the league's own Optic config, or the
    # pass would match poly markets against another league's fixture list.
    assert cfg.optic_league_id == LEAGUES[league].OPTIC.league_id
    assert cfg.question_style == "mlb_suffix"


def test_slug_prefixes_are_unique_across_leagues():
    """Two leagues sharing a prefix would both claim the same bridge slugs.

    (Tennis legitimately shares prefixes -- atp/atp_challenger both use "atp",
    itf_men/itf_women both use "itf" -- separated only by optic league_id, so
    this check is scoped to the soccer competitions wired here.)
    """
    seen = {}
    for league, prefix, _optic in _PAIRINGS:
        assert prefix not in seen, f"{league} collides with {seen.get(prefix)}"
        seen[prefix] = league


def test_col_is_the_conference_league_not_colombia():
    """`col` is UEFA's third competition. Polymarket files Colombia's Primera A
    under `col1`; binding `col` to a Colombian league would mis-stamp every
    Conference League token."""
    cfg = LEAGUES["europa_conference_league"].POLYMARKET
    assert cfg is not None
    assert cfg.slug_prefix == "col"
    assert "uefa" in cfg.optic_league_id
    assert "colombia" not in cfg.optic_league_id


# --- shared UEFA alias table invariants ---


@pytest.mark.parametrize("poly,optic,why", _PAIRS, ids=lambda v: str(v))
def test_every_uefa_alias_flips_the_matcher(poly, optic, why):
    """Each alias must actually change the outcome: names must NOT already match
    (else it is dead weight) and MUST match under the overlay."""
    poly_n = pm._norm_name(poly, "mlb_suffix")
    assert not pm._match_name(poly_n, optic, "mlb_suffix", "full"), (
        f"alias {poly!r}->{optic!r} ({why}) is redundant: names already match"
    )
    with pm.team_alias_scope(UEFA_TEAM_NAME_ALIASES):
        assert pm._match_name(poly_n, optic, "mlb_suffix", "full"), (
            f"alias {poly!r}->{optic!r} ({why}) does not resolve"
        )


def test_uefa_aliases_are_a_function_not_a_merge():
    """No alias may chain: a target that is itself a key makes resolution
    order-dependent (_name_match rewrites BOTH sides through the overlay)."""
    targets = set(UEFA_TEAM_NAME_ALIASES.values())
    assert not (targets & set(UEFA_TEAM_NAME_ALIASES)), "alias chain"
    assert len(UEFA_TEAM_NAME_ALIASES) == len(_PAIRS) + len(_DISAMBIGUATE_PAIRS)


def test_uefa_aliases_never_bind_the_two_cska_sofia_clubs():
    """Optic carries PFK CSKA Sofia and FK CSKA 1948 Sofia as distinct clubs,
    and mlb_suffix matching is containment-based, so any CSKA alias risks
    binding the wrong one. Both already match exactly; none may be added."""
    for poly, optic, _why in _PAIRS + _DISAMBIGUATE_PAIRS:
        assert "cska" not in pm._norm_name(poly, "mlb_suffix")
        assert "cska" not in pm._norm_name(optic, "mlb_suffix")


def test_all_three_uefa_competitions_share_the_alias_table():
    """UEFA qualifying drops losers a tier, so the same club appears across
    all three competitions — one shared vocab table, or it goes stale on
    relegation. Classify reads those names from the tip; the grammar table
    stays the single source for matcher tests.
    """
    assert UEFA_TEAM_NAME_ALIASES
    for slug in ("ucl", "europa_league", "europa_conference_league"):
        assert LEAGUES[slug].POLYMARKET is not None


@pytest.mark.parametrize(
    "poly_name,optic_name",
    [
        # Live UCL gaps this table fixes (poly bridge x optic fixtures, 08-04/08-11).
        ("NEC", "Nijmegen Eendracht Combinatie"),
        ("Olympiakós SFP", "Olympiakos CFP"),
        ("RU Saint-Gilloise", "Royale Union Saint-Gilloise"),
    ],
)
def test_new_ucl_aliases_resolve_a_real_fixture(poly_name, optic_name):
    cfg = LEAGUES["ucl"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX(optic_name, "NK Celje", "2026-08-11T18:00:00Z")]
    parsed = _parsed(poly_name, "NK Celje", "2026-08-11")
    with pm.team_alias_scope(UEFA_TEAM_NAME_ALIASES):
        assert _match_poly_fixture(parsed, fixtures, cfg.question_style) is fixtures[0]


# --- Leagues Cup: the alias table is the union of its two feeder leagues ---


def test_leagues_cup_aliases_are_the_mls_liga_mx_union():
    """Leagues Cup aliases are the union of MLS and Liga MX tip aliases."""
    cup = _poly_name_aliases("leagues_cup")
    mls = _poly_name_aliases("mls")
    liga = _poly_name_aliases("liga_mx")
    assert cup
    missing = sorted((set(mls) | set(liga)) - set(cup))
    assert not missing, f"leagues_cup missing feeder aliases: {missing}"
    assert not (set(mls) & set(liga))


@pytest.mark.parametrize(
    "poly_name,optic_name",
    [
        # Real 2026 Leagues Cup entrants whose poly and optic names share no
        # containment substring — verified on the live bridge x optic pull.
        ("Inter Miami CF", "Club Internacional de Fútbol Miami"),
        ("CF América", "Club de Fútbol América"),
        ("Pumas de la UNAM", "Pumas de la Universidad Nacional Autonoma de Mexico"),
        ("Tigres de la UANL", "Club Tigres de la Universidad Autónoma de Nuevo León"),
        ("New York City FC", "New York City Football Club"),
    ],
)
def test_leagues_cup_alias_resolves_fixture(poly_name, optic_name):
    cfg = LEAGUES["leagues_cup"].POLYMARKET
    assert cfg is not None
    fixtures = [_FX(optic_name, "Austin FC", "2026-08-13T23:30:00Z")]
    parsed = _parsed(poly_name, "Austin FC", "2026-08-13")
    with pm.team_alias_scope(_poly_name_aliases("leagues_cup")):
        assert _match_poly_fixture(parsed, fixtures, cfg.question_style) is fixtures[0]


@pytest.mark.parametrize(
    "poly_name,optic_name",
    [
        ("Inter Miami CF", "Club Internacional de Fútbol Miami"),
        ("Pumas de la UNAM", "Pumas de la Universidad Nacional Autonoma de Mexico"),
    ],
)
def test_leagues_cup_alias_without_scope_does_not_match(poly_name, optic_name):
    """Guards that the overlay — not plain containment — is doing the work."""
    fixtures = [_FX(optic_name, "Austin FC", "2026-08-13T23:30:00Z")]
    parsed = _parsed(poly_name, "Austin FC", "2026-08-13")
    assert _match_poly_fixture(parsed, fixtures, "mlb_suffix") is None


# --- OFI ⊂ sofia: containment collision on CSKA Sofia v OFI FC ---

_CSK_HOME = "PFK CSKA Sofia"
_OFI_AWAY = "OFI FC"


def _uel_cfg() -> pm.PolymarketConfig:
    cfg = LEAGUES["europa_league"].POLYMARKET
    assert cfg is not None
    return cfg


def _uel_yesno(question: str) -> pm.PolyMarket:
    return pm.PolyMarket(
        condition_id="0xuel",
        slug="uel-csk1-ofi-2026-08-27",
        question=question,
        outcomes=[
            pm.PolyOutcome(
                clob_token_id="cY", position_id="pY",
                outcome_label="Yes", outcome_index=0,
            ),
            pm.PolyOutcome(
                clob_token_id="cN", position_id="pN",
                outcome_label="No", outcome_index=1,
            ),
        ],
    )


def _uel_ou(question: str) -> pm.PolyMarket:
    return pm.PolyMarket(
        condition_id="0xuel",
        slug="uel-csk1-ofi-2026-08-27-team-total-away-0pt5",
        question=question,
        outcomes=[
            pm.PolyOutcome(
                clob_token_id="cO", position_id="pO",
                outcome_label="Over", outcome_index=0,
            ),
            pm.PolyOutcome(
                clob_token_id="cU", position_id="pU",
                outcome_label="Under", outcome_index=1,
            ),
        ],
    )


def _build_csk_ofi(market: pm.PolyMarket, parsed: pm.ParsedMarket):
    return pm.build_rows(
        market, parsed, home="CSK", away="OFI",
        home_name=_CSK_HOME, away_name=_OFI_AWAY,
        start_date="2026-08-27T18:00:00Z",
        cfg=_uel_cfg(), league="europa_league",
    )


def test_ofi_hits_both_fixture_sides_without_alias():
    """Root cause: 'ofi' is a substring of 'sofia' and of 'ofi fc'."""
    ofi = pm._norm_name("OFI", "mlb_suffix")
    assert pm._unique_fixture_side(
        ofi, home="CSK", away="OFI",
        home_name=_CSK_HOME, away_name=_OFI_AWAY, style="mlb_suffix",
    ) is None


def test_ofi_alias_uniquely_matches_away():
    ofi = pm._norm_name("OFI", "mlb_suffix")
    with pm.team_alias_scope(UEFA_TEAM_NAME_ALIASES):
        assert pm._unique_fixture_side(
            ofi, home="CSK", away="OFI",
            home_name=_CSK_HOME, away_name=_OFI_AWAY, style="mlb_suffix",
        ) == "OFI"


def test_cska_sofia_still_uniquely_home():
    cska = pm._norm_name(_CSK_HOME, "mlb_suffix")
    with pm.team_alias_scope(UEFA_TEAM_NAME_ALIASES):
        assert pm._unique_fixture_side(
            cska, home="CSK", away="OFI",
            home_name=_CSK_HOME, away_name=_OFI_AWAY, style="mlb_suffix",
        ) == "CSK"


def test_ofi_named_market_does_not_bind_cska_without_alias():
    m = _uel_yesno("OFI leading at halftime?")
    parsed = pm.soccer_first_half_leader_rule(m.question, _uel_cfg())
    assert parsed is not None
    assert _build_csk_ofi(m, parsed) == []


@pytest.mark.parametrize(
    "question,rule,side,market_type",
    [
        ("Will OFI win on 2026-08-27?", pm.soccer_ml_team_win_rule, "OFI", "moneyline_3way"),
        ("OFI leading at halftime?", pm.soccer_first_half_leader_rule, "OFI", "1h_winner_3way"),
        ("OFI to win the second half?", pm.soccer_second_half_winner_rule, "OFI", "2h_winner_3way"),
        ("Will PFK CSKA Sofia win on 2026-08-27?", pm.soccer_ml_team_win_rule, "CSK", "moneyline_3way"),
        ("PFK CSKA Sofia leading at halftime?", pm.soccer_first_half_leader_rule, "CSK", "1h_winner_3way"),
    ],
)
def test_uel_csk_ofi_sides_with_alias(question, rule, side, market_type):
    m = _uel_yesno(question)
    parsed = rule(m.question, _uel_cfg())
    assert parsed is not None
    with pm.team_alias_scope(UEFA_TEAM_NAME_ALIASES):
        rows = _build_csk_ofi(m, parsed)
    assert len(rows) == 1
    assert rows[0].side == side
    assert rows[0].market_type == market_type
    assert rows[0].polymarket_clob_token_id == "cY"


def test_ofi_team_total_binds_away_not_cska():
    m = _uel_ou("PFK CSKA Sofia vs. OFI: OFI O/U 0.5")
    parsed = pm.soccer_team_total_rule(m.question, _uel_cfg())
    assert parsed is not None
    with pm.team_alias_scope(UEFA_TEAM_NAME_ALIASES):
        rows = _build_csk_ofi(m, parsed)
    assert {r.side: r.entity for r in rows} == {"over": "OFI", "under": "OFI"}


def test_disambiguate_pairs_already_match_intended_optic():
    """Unlike _PAIRS, these aliases exist to break a false hit, not create one."""
    for poly, optic, _why in _DISAMBIGUATE_PAIRS:
        poly_n = pm._norm_name(poly, "mlb_suffix")
        assert pm._match_name(poly_n, optic, "mlb_suffix", "full")
        with pm.team_alias_scope(UEFA_TEAM_NAME_ALIASES):
            assert pm._match_name(poly_n, optic, "mlb_suffix", "full")
            assert not pm._match_name(poly_n, _CSK_HOME, "mlb_suffix", "full")
