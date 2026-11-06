"""Tests for UFC and Liga MX league configs and crypto fight-line parsing."""

from __future__ import annotations

from mappers.exchanges.crypto_com import (
    FIGHT_LINE,
    FIGHT_PROP,
    Selection,
    build_rows,
    to_selection_record,
)
from mappers.exchanges.kalshi import Market
from mappers.exchanges.kalshi import build_rows as kalshi_build_rows
from mappers.exchanges.optic import (
    Fixture,
    Odd,
    OpticConfig,
)
from mappers.exchanges.optic import build_rows as optic_build_rows
from mappers.fight_props import canonicalize_fight_prop_key
from mappers.market_types import MarketType
from mappers.pipeline import row_key
from mappers.run import LEAGUES
from mappers.sport import Sport, sport_for_league
from tests.mappers._combat_helpers import (
    UFC_KALSHI,
    UFC_OPTIC,
    ufc_league_config,
)


def test_new_leagues_registered():
    assert "liga_mx" in LEAGUES
    assert sport_for_league("ufc") == Sport.MMA
    assert sport_for_league("liga_mx") == Sport.SOCCER


def test_liga_mx_crypto_uses_lmx_meta_league():
    assert LEAGUES['liga_mx'].CRYPTO is not None
    assert LEAGUES['liga_mx'].CRYPTO.league == "LMX"
    assert LEAGUES['liga_mx'].OPTIC.league_id == "mexico_-_liga_mx"
    assert LEAGUES['liga_mx'].PX is None


def test_ufc_crypto_fight_vocabulary():
    ufc_cfg = ufc_league_config()
    crypto = ufc_cfg.CRYPTO
    assert crypto is not None
    assert crypto.league == "UFC"
    assert crypto.sport_grouping == "MMA"
    assert crypto.period_type == "Full Fight"
    assert crypto.contract_types["Moneyline"] == MarketType.MONEYLINE
    assert "Round of Victory" in crypto.game_prop_contract_types
    # Method of Victory / Finish stay off crypto (Kalshi↔Optic only).
    assert "Method of Victory" not in crypto.game_prop_contract_types
    assert "Method of Finish" not in crypto.game_prop_contract_types
    assert crypto.game_prop_accept_round_periods is True
    assert ufc_cfg.OPTIC.league_id == "ufc"
    assert ufc_cfg.PX is None


def test_from_fix_meta_league_includes_ufc_and_liga_mx():
    expected = {
        "ufc": "UFC",
        "liga_mx": "LMX",
        "mls": "MLS",
        "europa_league": "UEL",
        "europa_conference_league": "UCOL",
        "argentina_primera": "ARP",
        "brazil_serie_a": "BRSA",
    }
    for slug, meta in expected.items():
        crypto = LEAGUES[slug].CRYPTO
        assert crypto is not None, slug
        assert crypto.league == meta, slug


def test_fight_line_to_selection_synthesizes_game_id():
    flat = {
        "SecurityID": "UFC-ML-1",
        "Symbol": "NX.F.OPT.UFC-00013-260725-M.O.1.1.20261231",
        "eventMetaLEAGUE": "UFC",
        "eventMetaSPORTS_GROUPING": "MMA",
        "eventMetaEVENT_DATE": "2026-07-25T13:15:00+00:00",
        "eventMetaHOME_PARTICIPANT": "Cody Gibson",
        "eventMetaAWAY_PARTICIPANT": "Abdul Hussein",
        "eventMetaEXTERNAL_HOME_ID": "140002905",
        "eventMetaEXTERNAL_AWAY_ID": "140005773",
        "eventMetaPREDICT_MARKET_TYPE": FIGHT_LINE,
        "eventMetaPREDICT_CONTRACT_TYPE": "Moneyline",
        "eventMetaPREDICT_PERIOD_TYPE": "Full Fight",
        "eventMetaPARTICIPANT": "Cody Gibson",
        "eventMetaPLAYER_ID": "140002905",
        "eventMetaPREDICT_MARKET_ID": "m1",
        "eventMetaPREDICT_OUTCOME_ID": "o1",
        "eventName": "Cody Gibson to win",
    }
    rec = to_selection_record(flat)
    assert rec is not None
    assert rec["external_game_id"] == "NX.F.OPT.UFC-00013-260725"
    assert rec["market_group"] == FIGHT_LINE
    assert rec["outcome_type"] is None


def test_ufc_fight_moneyline_build_rows_resolves_side_from_player_id():
    cfg = ufc_league_config().CRYPTO
    assert cfg is not None
    aliases = {
        "140002905": "GIB",
        "140005773": "HUS",
    }
    sels = [
        Selection(
            security_id="1",
            symbol="NX.F.OPT.UFC-00013-260725-M.O.1.1.20261231",
            league="UFC",
            sport="MMA",
            start_date="2026-07-25T13:15:00+00:00",
            home_participant="Cody Gibson",
            away_participant="Abdul Hussein",
            external_home_id="140002905",
            external_away_id="140005773",
            external_game_id="NX.F.OPT.UFC-00013-260725",
            market_group=FIGHT_LINE,
            contract_type="Moneyline",
            period="Full Fight",
            outcome_type=None,
            value=None,
            selection_name="Cody Gibson to win",
            crypto_market_id="m1",
            crypto_outcome_id="o1",
            participant="Cody Gibson",
            player_id="140002905",
        ),
        Selection(
            security_id="2",
            symbol="NX.F.OPT.UFC-00013-260725-M.O.1.2.20261231",
            league="UFC",
            sport="MMA",
            start_date="2026-07-25T13:15:00+00:00",
            home_participant="Cody Gibson",
            away_participant="Abdul Hussein",
            external_home_id="140002905",
            external_away_id="140005773",
            external_game_id="NX.F.OPT.UFC-00013-260725",
            market_group=FIGHT_LINE,
            contract_type="Moneyline",
            period="Full Fight",
            outcome_type=None,
            value=None,
            selection_name="Abdul Hussein to win",
            crypto_market_id="m1",
            crypto_outcome_id="o2",
            participant="Abdul Hussein",
            player_id="140005773",
        ),
    ]
    rows = build_rows(
        "2026-07-25T13:15:00+00:00", "GIB", "HUS", sels, cfg,
        aliases=aliases, league="ufc",
        fixture_names={"GIB": "Cody Gibson", "HUS": "Abdul Hussein"},
    )
    assert {(r.side, r.market_type) for r in rows} == {
        ("GIB", "moneyline"),
        ("HUS", "moneyline"),
    }
    # Person leagues fail closed without the Optic names to check against.
    assert build_rows(
        "2026-07-25T13:15:00+00:00", "GIB", "HUS", sels, cfg,
        aliases=aliases, league="ufc",
    ) == []


def test_ufc_crossed_crypto_ids_do_not_stamp() -> None:
    """Song's id on Umar's canonical must not invert moneyline sides."""
    cfg = ufc_league_config().CRYPTO
    assert cfg is not None
    aliases = {"140002905": "HUS", "140005773": "GIB"}
    names = {"GIB": "Cody Gibson", "HUS": "Abdul Hussein"}
    skipped: list[str] = []
    sel = Selection(
        security_id="1",
        symbol="NX.F.OPT.UFC-00013-260725-M.O.1.1.20261231",
        league="UFC",
        sport="MMA",
        start_date="2026-07-25T13:15:00+00:00",
        home_participant="Cody Gibson",
        away_participant="Abdul Hussein",
        external_home_id="140002905",
        external_away_id="140005773",
        external_game_id="NX.F.OPT.UFC-00013-260725",
        market_group=FIGHT_LINE,
        contract_type="Moneyline",
        period="Full Fight",
        outcome_type=None,
        value=None,
        selection_name="Cody Gibson to win",
        crypto_market_id="m1",
        crypto_outcome_id="o1",
        participant="Cody Gibson",
        player_id="140002905",
    )
    rows = build_rows(
        "2026-07-25T13:15:00+00:00", "GIB", "HUS", [sel], cfg,
        aliases=aliases, league="ufc", entity_names=names,
        skipped_name_mismatch=skipped,
    )
    assert rows == []
    assert skipped


def test_ufc_fight_prop_uses_grouping_key():
    """Round of Victory reconciles with Optic round_betting via the round-key
    canonicalizer (crypto labels the outcome "<Fighter> to win in Round N")."""
    cfg = ufc_league_config().CRYPTO
    assert cfg is not None
    aliases = {"140002905": "GIB", "140005773": "HUS"}
    sel = Selection(
        security_id="3",
        symbol="NX.F.OPT.UFC-00001-260711-M.O.3.25.20261231",
        league="UFC",
        sport="MMA",
        start_date="2026-07-12T04:15:00+00:00",
        home_participant="Max Holloway",
        away_participant="Conor McGregor",
        external_home_id="140002905",
        external_away_id="140005773",
        external_game_id="NX.F.OPT.UFC-00001-260711",
        market_group=FIGHT_PROP,
        contract_type="Round of Victory",
        period="Round 1",
        outcome_type=None,
        value=None,
        selection_name="Max Holloway to win in Round 1",
        crypto_market_id="m3",
        crypto_outcome_id="o3",
        participant="Max Holloway to win in Round 1",
    )
    rows = build_rows(
        "2026-07-12T04:15:00+00:00", "GIB", "HUS", [sel], cfg,
        aliases=aliases, league="ufc",
    )
    assert len(rows) == 1
    assert rows[0].market_type == "round_betting"
    assert rows[0].side == "yes"
    assert rows[0].grouping_key == "max_holloway_round_1"


def _fight_prop_sel(
    *,
    participant: str,
    outcome_type: str | None,
    contract_type: str = "Round of Victory",
    security_id: str = "202608131537460701042538D",
) -> Selection:
    """A live-shape UFC fight prop (2026-08-15 Makhachev vs Machado Garry).

    Since 2026-08-13 the feed stamps every fight prop with period "Full
    Fight" and names the fighter on PREDICT_OUTCOME_TYPE (Home/Away/Draw);
    the round lives only in the PARTICIPANT label.
    """
    return Selection(
        security_id=security_id,
        symbol="NX.F.OPT.UFC-00001-260815-M.O.1.31.20261231",
        league="UFC",
        sport="MMA",
        start_date="2026-08-16T02:00:00+00:00",
        home_participant="Ian Machado Garry",
        away_participant="Islam Makhachev",
        external_home_id="140001217",
        external_away_id="140000285",
        external_game_id="NX.F.OPT.UFC-00001-260815",
        market_group=FIGHT_PROP,
        contract_type=contract_type,
        period="Full Fight",
        outcome_type=outcome_type,
        value=None,
        selection_name=f"{participant} to win",
        crypto_market_id="m5",
        crypto_outcome_id="o5",
        participant=participant,
    )


def _fight_prop_rows(sel: Selection):
    cfg = ufc_league_config().CRYPTO
    assert cfg is not None
    return build_rows(
        "2026-08-16T02:00:00+00:00", "GAR", "MAK", [sel], cfg,
        aliases={"140001217": "GAR", "140000285": "MAK"}, league="ufc",
    )


def test_ufc_round_of_victory_keys_on_label_not_fighter_outcome():
    """The Home/Away outcome_type names the fighter the label already names,
    so the round key is unchanged and the leg stays a yes-side question."""
    rows = _fight_prop_rows(_fight_prop_sel(
        participant="Islam Makhachev to win in Round 3",
        outcome_type="Away",
    ))
    assert len(rows) == 1
    assert rows[0].market_type == "round_betting"
    assert rows[0].side == "yes"
    assert rows[0].grouping_key == "islam_makhachev_round_3"


def test_ufc_round_of_victory_roundless_label_is_skipped():
    """One re-listing wave fills the round slot from the period field, so all
    five of a fighter's legs read "to win in Full Fight".  The round is
    unrecoverable, so the leg is dropped rather than keyed without it."""
    assert _fight_prop_rows(_fight_prop_sel(
        participant="Islam Makhachev to win in Full Fight",
        outcome_type="Away",
    )) == []


def test_ufc_fight_prop_draw_leg_stays_distinct_from_optic_draw():
    """crypto's draw leg also settles on a decision, so its key must not
    collapse onto Optic round_betting's bare "draw"."""
    rows = _fight_prop_rows(_fight_prop_sel(
        participant="Decision / Draw / No Contest",
        outcome_type="Draw",
    ))
    assert len(rows) == 1
    assert rows[0].side == "yes"
    assert rows[0].grouping_key != canonicalize_fight_prop_key("Draw")


def test_ufc_fight_prop_novel_outcome_type_is_skipped_not_raised():
    """A novel fight-prop outcome_type costs its own leg, never the league's
    whole tick (2026-08-13: 'Away' raised and UFC produced no rows)."""
    assert _fight_prop_rows(_fight_prop_sel(
        participant="Islam Makhachev to win in Round 3",
        outcome_type="Over",
    )) == []


def test_fight_prop_round_keys_reconcile_optic_and_crypto():
    assert canonicalize_fight_prop_key("Juliana Miller :: 1st Round") == (
        canonicalize_fight_prop_key("Juliana Miller to win in Round 1")
    )
    assert canonicalize_fight_prop_key(
        "Juliana Miller to win in Round 1"
    ) == "juliana_miller_round_1"


def test_ufc_go_the_distance_omits_grouping_key():
    cfg = ufc_league_config().CRYPTO
    assert cfg is not None
    aliases = {"140002905": "GIB", "140005773": "HUS"}
    sel = Selection(
        security_id="4",
        symbol="NX.F.OPT.UFC-00001-260711-M.O.3.1.20261231",
        league="UFC",
        sport="MMA",
        start_date="2026-07-12T04:15:00+00:00",
        home_participant="Max Holloway",
        away_participant="Conor McGregor",
        external_home_id="140002905",
        external_away_id="140005773",
        external_game_id="NX.F.OPT.UFC-00001-260711",
        market_group=FIGHT_PROP,
        contract_type="Fight To Go The Distance",
        period="Full Fight",
        outcome_type=None,
        value=None,
        selection_name="Fight To Go The Distance",
        crypto_market_id="m4",
        crypto_outcome_id="o4",
        participant="Yes",
    )
    rows = build_rows(
        "2026-07-12T04:15:00+00:00", "GIB", "HUS", [sel], cfg,
        aliases=aliases, league="ufc",
    )
    assert len(rows) == 1
    assert rows[0].market_type == "fight_goes_distance"
    assert rows[0].side == "yes"
    assert rows[0].grouping_key is None


def test_optic_method_of_victory_maps_mergable_skips_extras():
    """Optic method_of_victory emits Kalshi-mergable buckets plus ``ko_tko``
    (Polymarket US ``mov-f*-ko``). Draw stays skipped."""
    fixture = Fixture(
        fixture_id="f1",
        game_id="g1",
        sportradar_id=None,
        start_et="2026-07-25T09:15:00",
        start_date="2026-07-25T13:15:00+00:00",
        home="GIB",
        away="HUS",
        home_name="Cody Gibson",
        away_name="Abdul Hussein",
        team_map={"t1": "GIB", "t2": "HUS"},
        odds=[
            Odd(
                id="22133-17237-2026-07:method_of_victory:abdul_hussein-_-ko_tko_dq",
                market="Method of Victory",
                name="Abdul Hussein - KO/TKO/DQ",
                selection="Abdul Hussein",
                normalized_selection="abdul_hussein",
                market_id="method_of_victory",
                selection_line=None,
                player_id=None,
                team_id="t2",
                grouping_key="default",
                points=None,
                source_ids={},
            ),
            Odd(
                id="22133-17237-2026-07:method_of_victory:cody_gibson-_-decision",
                market="Method of Victory",
                name="Cody Gibson - Decision",
                selection="Cody Gibson",
                normalized_selection="cody_gibson",
                market_id="method_of_victory",
                selection_line=None,
                player_id=None,
                team_id="t1",
                grouping_key="default",
                points=None,
                source_ids={},
            ),
            Odd(
                id="22133-17237-2026-07:method_of_victory:abdul_hussein-_-ko_tko",
                market="Method of Victory",
                name="Abdul Hussein - KO/TKO",
                selection="Abdul Hussein",
                normalized_selection="abdul_hussein",
                market_id="method_of_victory",
                selection_line=None,
                player_id=None,
                team_id="t2",
                grouping_key="default",
                points=None,
                source_ids={},
            ),
            Odd(
                id="22133-17237-2026-07:method_of_victory:draw",
                market="Method of Victory",
                name="Draw",
                selection="",
                normalized_selection="",
                market_id="method_of_victory",
                selection_line=None,
                player_id=None,
                team_id=None,
                grouping_key="default",
                points=None,
                source_ids={},
            ),
            Odd(
                id="f1:method_of_ending:ko_tko_dq",
                market="Method of Ending",
                name="KO/TKO/DQ",
                selection="ko_tko_dq",
                normalized_selection="ko_tko_dq",
                market_id="method_of_ending",
                selection_line=None,
                player_id=None,
                team_id=None,
                grouping_key="default",
                points=None,
                source_ids={},
            ),
        ],
        is_live=False,
    )
    rows, _, _ = optic_build_rows(
        "2026-07-25T13:15:00+00:00", "GIB", "HUS", fixture, UFC_OPTIC,
        league="ufc",
    )
    assert {(r.market_type, r.entity, r.grouping_key, r.side) for r in rows} == {
        ("method_of_victory", "HUS", "ko_tko_dq", "yes"),
        ("method_of_victory", "GIB", "decision", "yes"),
        ("method_of_victory", "HUS", "ko_tko", "yes"),
        ("method_of_finish", None, "ko_tko_dq", "yes"),
    }


_UFC_MILESTONE = {"id": "ms", "home_id": "gib-id", "away_id": "hus-id"}


def _ufc_market(
    event_ticker: str,
    ticker: str,
    scope: str,
    *,
    title: str,
    sub_title: str,
    custom_strike: dict | None = None,
) -> Market:
    """A Kalshi UFC market typed by scope, strike and milestone."""
    return Market(
        event_ticker=event_ticker,
        ticker=ticker,
        title=title,
        yes_sub_title=sub_title,
        no_sub_title=sub_title,
        competition_scope=scope,
        series_scope=scope,
        custom_strike=custom_strike,
        milestone=_UFC_MILESTONE,
    )


def test_kalshi_optic_mov_row_keys_merge():
    """Kalshi MOV yes-leg and Optic method_of_victory share row_key."""
    et = "KXUFCMOV-26AUG08GIBHUS"
    kalshi_rows = kalshi_build_rows(
        start_date="2026-08-08T00:00:00+00:00",
        home="GIB", away="HUS",
        markets=[_ufc_market(
            et, f"{et}-HUSKOTKODQ", "Method of Victory",
            title="Will Abdul Hussein win by KO/TKO/DQ?",
            sub_title="Abdul Hussein by KO/TKO/DQ",
            custom_strike={"Method": "KO/TKO/DQ", "ufc_competitor": "hus-id"},
        )],
        cfg=UFC_KALSHI,
        league="ufc",
    )
    k_yes = next(r for r in kalshi_rows if r.side == "yes")

    fixture = Fixture(
        fixture_id="f1",
        game_id="g1",
        sportradar_id=None,
        start_et="2026-08-08T00:00:00",
        start_date="2026-08-08T00:00:00+00:00",
        home="GIB",
        away="HUS",
        home_name="Cody Gibson",
        away_name="Abdul Hussein",
        team_map={"t1": "GIB", "t2": "HUS"},
        odds=[
            Odd(
                id="o1",
                market="Method of Victory",
                name="Abdul Hussein - KO/TKO/DQ",
                selection="Abdul Hussein",
                normalized_selection="abdul_hussein",
                market_id="method_of_victory",
                selection_line=None,
                player_id=None,
                team_id="t2",
                grouping_key="default",
                points=None,
                source_ids={},
            ),
        ],
        is_live=False,
    )
    optic_rows, _, _ = optic_build_rows(
        "2026-08-08T00:00:00+00:00", "GIB", "HUS", fixture, UFC_OPTIC,
        league="ufc",
    )
    assert len(optic_rows) == 1
    assert row_key(k_yes) == row_key(optic_rows[0])


def test_kalshi_optic_rounds_row_keys_merge():
    """'Fight ends before round 2' Yes lands on Optic to_start_round_2 No."""
    et = "KXUFCROUNDS-26AUG08GIBHUS"
    kalshi_rows = kalshi_build_rows(
        start_date="2026-08-08T00:00:00+00:00",
        home="GIB", away="HUS",
        markets=[_ufc_market(
            et, f"{et}-2", "Round of Finish",
            title="Will the Fight end before round 2?",
            sub_title="Fight ends before round 2",
        )],
        cfg=UFC_KALSHI,
        league="ufc",
    )
    by_kalshi_side = {r.kalshi_side: r for r in kalshi_rows}

    def odd(sel: str) -> Odd:
        return Odd(
            id=f"g1:to_start_round_2:{sel}",
            market="To Start Round 2",
            name=sel.title(),
            selection=sel.title(),
            normalized_selection=sel,
            market_id="to_start_round_2",
            selection_line=None,
            player_id=None,
            team_id=None,
            grouping_key="default",
            points=None,
            source_ids={},
        )

    fixture = Fixture(
        fixture_id="f1",
        game_id="g1",
        sportradar_id=None,
        start_et="2026-08-08T00:00:00",
        start_date="2026-08-08T00:00:00+00:00",
        home="GIB",
        away="HUS",
        home_name="Cody Gibson",
        away_name="Abdul Hussein",
        team_map={"t1": "GIB", "t2": "HUS"},
        odds=[odd("yes"), odd("no")],
        is_live=False,
    )
    optic_rows, _, _ = optic_build_rows(
        "2026-08-08T00:00:00+00:00", "GIB", "HUS", fixture, UFC_OPTIC,
        league="ufc",
    )
    o_by_side = {r.side: r for r in optic_rows}
    assert row_key(by_kalshi_side["yes"]) == row_key(o_by_side["no"])
    assert row_key(by_kalshi_side["no"]) == row_key(o_by_side["yes"])


def test_kalshi_optic_distance_row_keys_merge():
    et = "KXUFCDISTANCE-26AUG08GIBHUS"
    kalshi_rows = kalshi_build_rows(
        start_date="2026-08-08T00:00:00+00:00",
        home="GIB", away="HUS",
        markets=[_ufc_market(
            et, f"{et}-DIST", "Go the Distance",
            title="Fight goes the distance?",
            sub_title="Fight goes the distance",
        )],
        cfg=UFC_KALSHI,
        league="ufc",
    )
    k_yes = next(r for r in kalshi_rows if r.side == "yes")

    fixture = Fixture(
        fixture_id="f1",
        game_id="g1",
        sportradar_id=None,
        start_et="2026-08-08T00:00:00",
        start_date="2026-08-08T00:00:00+00:00",
        home="GIB",
        away="HUS",
        home_name="Cody Gibson",
        away_name="Abdul Hussein",
        team_map={"t1": "GIB", "t2": "HUS"},
        odds=[
            Odd(
                id="o-gtd",
                market="Fight To Go The Distance",
                name="Yes",
                selection="",
                normalized_selection="",
                market_id="go_the_distance",
                selection_line=None,
                player_id=None,
                team_id=None,
                grouping_key="default",
                points=None,
                source_ids={},
            ),
        ],
        is_live=False,
    )
    optic_rows, _, _ = optic_build_rows(
        "2026-08-08T00:00:00+00:00", "GIB", "HUS", fixture, UFC_OPTIC,
        league="ufc",
    )
    assert len(optic_rows) == 1
    assert row_key(k_yes) == row_key(optic_rows[0])
    assert k_yes.grouping_key is None


def test_kalshi_optic_vicround_row_keys_merge():
    et = "KXUFCVICROUND-26AUG08GIBHUS"
    kalshi_rows = kalshi_build_rows(
        start_date="2026-08-08T00:00:00+00:00",
        home="GIB", away="HUS",
        markets=[_ufc_market(
            et, f"{et}-HUS2", "Round of Victory",
            title="Will Abdul Hussein win in Round 2?",
            sub_title="Abdul Hussein to win in Round 2",
            custom_strike={"Round": "2", "ufc_competitor": "hus-id"},
        )],
        cfg=UFC_KALSHI,
        league="ufc",
    )
    k_yes = next(r for r in kalshi_rows if r.side == "yes")

    fixture = Fixture(
        fixture_id="f1",
        game_id="g1",
        sportradar_id=None,
        start_et="2026-08-08T00:00:00",
        start_date="2026-08-08T00:00:00+00:00",
        home="GIB",
        away="HUS",
        home_name="Cody Gibson",
        away_name="Abdul Hussein",
        team_map={"t1": "GIB", "t2": "HUS"},
        odds=[
            Odd(
                id="o-r2",
                market="Round Betting",
                name="Abdul Hussein :: 2nd Round",
                selection="Abdul Hussein 2nd Round",
                normalized_selection="abdul_hussein_2nd_round",
                market_id="round_betting",
                selection_line=None,
                player_id=None,
                team_id=None,
                grouping_key="default",
                points=None,
                source_ids={},
            ),
        ],
        is_live=False,
    )
    optic_rows, _, _ = optic_build_rows(
        "2026-08-08T00:00:00+00:00", "GIB", "HUS", fixture, UFC_OPTIC,
        league="ufc",
    )
    assert len(optic_rows) == 1
    assert row_key(k_yes) == row_key(optic_rows[0])
    assert k_yes.grouping_key == "abdul_hussein_round_2"

def test_optic_round_betting_canonicalizes_grouping_key():
    fixture = Fixture(
        fixture_id="f2",
        game_id="g2",
        sportradar_id=None,
        start_et="2026-07-25T09:15:00",
        start_date="2026-07-25T13:15:00+00:00",
        home="GIB",
        away="HUS",
        home_name="Cody Gibson",
        away_name="Abdul Hussein",
        team_map={"t1": "GIB", "t2": "HUS"},
        odds=[
            Odd(
                id="f2:round:1",
                market="Round Betting",
                name="Cody Gibson :: 1st Round",
                selection="",
                normalized_selection="",
                market_id="round_betting",
                selection_line=None,
                player_id=None,
                team_id=None,
                grouping_key="default",
                points=None,
                source_ids={},
            ),
            Odd(
                id=(
                    "22133-17237-2026-07:round_betting:"
                    "abdul_hussein_3rd_round"
                ),
                market="Round Betting",
                name="Abdul Hussein :: 3rd Round",
                selection="Abdul Hussein 3rd Round",
                normalized_selection="abdul_hussein_3rd_round",
                market_id="round_betting",
                selection_line=None,
                player_id=None,
                team_id=None,
                grouping_key="default",
                points=None,
                source_ids={},
            ),
        ],
        is_live=False,
    )
    cfg = OpticConfig(
        league_id="ufc",
        table_types={"round_betting": MarketType.ROUND_BETTING},
    )
    rows, _, _ = optic_build_rows(
        "2026-07-25T13:15:00+00:00", "GIB", "HUS", fixture, cfg, league="ufc",
    )
    assert {row.grouping_key for row in rows} == {
        "cody_gibson_round_1",
        "abdul_hussein_round_3",
    }


def test_optic_round_betting_decision_and_draw_outcomes():
    """round_betting also ships non-round outcomes -- "<Fighter> :: Decision"
    and "Draw" -- alongside the "Nth Round" ones.  Live Optic data 2026-07-24
    (134 odds / 14 fixtures) has these with a populated selection; the
    ":: Decision" shape is exactly what crashed mappers.run before 7e11a2f.
    They must route through canonicalize_fight_prop_key (distinct grouping
    keys, side=yes), not raise.
    """
    def rb(oid: str, label: str) -> Odd:
        return Odd(
            id=oid, market="Round Betting", name=label,
            # Live shape: selection is populated (equals name here).
            selection=label, normalized_selection=label.lower().replace(" ", "_"),
            market_id="round_betting", selection_line=None,
            player_id=None, team_id=None, grouping_key="default",
            points=None, source_ids={},
        )
    fixture = Fixture(
        fixture_id="f3", game_id="g3", sportradar_id=None,
        start_et="2026-07-25T09:15:00", start_date="2026-07-25T13:15:00+00:00",
        home="GIB", away="HUS", home_name="Cody Gibson", away_name="Abdul Hussein",
        team_map={"t1": "GIB", "t2": "HUS"},
        odds=[
            rb("f3:r1", "Cody Gibson :: 1st Round"),
            rb("f3:dec", "Abdul Hussein :: Decision"),
            rb("f3:draw", "Draw"),
        ],
        is_live=False,
    )
    cfg = OpticConfig(
        league_id="ufc",
        table_types={"round_betting": MarketType.ROUND_BETTING},
    )
    rows, _, _ = optic_build_rows(
        "2026-07-25T13:15:00+00:00", "GIB", "HUS", fixture, cfg, league="ufc",
    )
    assert {r.grouping_key: r.side for r in rows} == {
        "cody_gibson_round_1": "yes",
        "abdul_hussein_::_decision": "yes",
        "draw": "yes",
    }
