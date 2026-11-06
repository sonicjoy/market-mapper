"""Tests for the crypto.com reshaping logic.

to_selection_record() (interpretive, mapper read-time: game-line gate +
field translation) and the processed-upstream catalogue builders are
covered here.  The BigQuery I/O (fetch_contracts/main) is exercised
manually against the live feed; this covers the reshaping, which is the
part that can silently go wrong.
"""

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from google.api_core.exceptions import NotFound

from fetch.crypto_com_identity import build_identity_index
from fetch.crypto_com_security_def import (
    SECURITY_DEF_QUERY,
    merge_security_def_contracts,
    security_def_row_to_flat,
)
from fetch.crypto_com_underlying import (
    CATALOGUE_EVENT_STALE_HOURS,
    CATALOGUE_WINDOW_MINUTES,
    UNDERLYING_CATALOGUE_QUERY,
    UNDERLYING_PROPS_QUERY,
    UnderlyingStats,
    fetch_underlying_props,
    synthesize_catalogue_records,
    synthesize_prop_records,
)
from fetch.crypto_com_underlying_flat import (
    infer_game_line_outcome,
    infer_player_prop_line_side,
    team_id_from_participant,
)
from mappers.exchanges.crypto_com import (
    build_rows,
    parse_selection,
    to_selection_record,
)
from mappers.run import LEAGUES
from tests.mappers._require import require

SOCCER_CRYPTO = require(LEAGUES["world_cup"].CRYPTO)


def _flat_contract(symbol, security_id, event_name, meta: dict, **extra) -> dict:
    """Build a flat catalogue dict as produced by the fetch layer."""
    out: dict = {
        "Symbol": symbol,
        "SecurityID": security_id,
        "eventName": event_name,
        "eventCode": security_id,
    }
    for key, value in meta.items():
        out["eventMeta" + key] = value
    out.update(extra)
    return out


# A game-line moneyline, a game-line total (with a line value), and a
# Team Future that must be dropped (no external_game_id, not a game line).
NBA_GAME = {
    "SPORTS_GROUPING": "BASKETBALL",
    "LEAGUE": "NBA",
    "HOME_PARTICIPANT": "New York Knicks",
    "AWAY_PARTICIPANT": "San Antonio Spurs",
    "EXTERNAL_HOME_ID": "20000006",
    "EXTERNAL_AWAY_ID": "20000024",
    "EXTERNAL_GAME_ID": "90012345",
    "EVENT_DATE": "2026-06-02T23:00:00+00:00",
    "PREDICT_PERIOD_TYPE": "Full Game",
}
ML_FLAT = _flat_contract(
    "NX.ML.H",
    "ML-001",
    "New York Knicks to win",
    {
        **NBA_GAME,
        "PREDICT_MARKET_TYPE": "Game Line",
        "PREDICT_CONTRACT_TYPE": "Moneyline",
        "PREDICT_OUTCOME_TYPE": "Home",
        "PREDICT_MARKET_ID": "MKT-1",
        "PREDICT_OUTCOME_ID": "OUT-1",
    },
)
TP_FLAT = _flat_contract(
    "NX.TP.O",
    "TP-001",
    "Over 214.5",
    {
        **NBA_GAME,
        "PREDICT_MARKET_TYPE": "Game Line",
        "PREDICT_CONTRACT_TYPE": "Total Points",
        "PREDICT_OUTCOME_TYPE": "Over",
        "PREDICT_VALUE": "214.5",
        "PREDICT_MARKET_ID": "MKT-2",
        "PREDICT_OUTCOME_ID": "OUT-2",
    },
)
FUT_FLAT = _flat_contract(
    "NX.FUT",
    "FUT-001",
    "Knicks to win title",
    {
        "SPORTS_GROUPING": "BASKETBALL",
        "LEAGUE": "NBA",
        "PREDICT_MARKET_TYPE": "Team Future",
    },
)
SPREAD_DEF_FLAT = _flat_contract(
    "NX.SP.A",
    "SP-001",
    "San Antonio Spurs +3.5",
    {
        **NBA_GAME,
        "PREDICT_MARKET_TYPE": "Game Line",
        "PREDICT_CONTRACT_TYPE": "Spread",
        "PREDICT_OUTCOME_TYPE": "Away",
        "PREDICT_VALUE": "3.5",
        "PREDICT_MARKET_ID": "MKT-3",
        "PREDICT_OUTCOME_ID": "OUT-3",
    },
    SecurityDesc="Knicks vs Spurs ; Spurs +3.5 ; Frost Bank Center",
    SecurityReqID="seclist_1780668515465",
)


def test_catalogue_window_spans_listing_to_kickoff():
    """The look-back must outlast crypto.com's ~14-day-ahead listing burst.

    A soccer fixture is listed once, roughly two weeks before kickoff, and
    never republished, while Optic only exposes it inside its 7-day fixture
    horizon.  A 7-day look-back therefore dropped the listing exactly as
    the fixture became mappable and MLS / La Liga produced no crypto rows.
    """
    assert CATALOGUE_WINDOW_MINUTES >= 14 * 24 * 60


def test_catalogue_queries_scope_to_live_fixtures():
    """Both sources filter on event date, so the wider window stays cheap.

    Without this the look-back would drag three weeks of finished fixtures
    into the catalogue file.  Unparseable/absent event dates are kept.
    """
    for sql in (UNDERLYING_CATALOGUE_QUERY, SECURITY_DEF_QUERY):
        assert "meta_event_date" in sql
        assert f"INTERVAL {CATALOGUE_EVENT_STALE_HOURS} HOUR" in sql
        assert "IS NULL" in sql
    # Wider windows must not multiply transferred rows: both queries
    # collapse to the newest listing per symbol / security id.
    assert "PARTITION BY symbol" in UNDERLYING_CATALOGUE_QUERY
    assert "PARTITION BY security_id" in SECURITY_DEF_QUERY


def test_props_query_alias_still_narrows_market_type():
    """The props alias is built by rewriting the catalogue query's filter."""
    assert 'meta_predict_market_type = "Player Prop"' in UNDERLYING_PROPS_QUERY
    assert "Game Line" not in UNDERLYING_PROPS_QUERY


def test_moneyline_record_has_no_line_value():
    rec = to_selection_record(ML_FLAT)
    assert rec is not None
    assert rec["value"] is None  # moneyline carries no PREDICT_VALUE
    assert rec["security_id"] == "ML-001"
    assert rec["external_home_id"] == "20000006"
    assert rec["outcome_type"] == "Home"


def test_total_record_coerces_value_to_float():
    rec = to_selection_record(TP_FLAT)
    assert rec is not None
    assert rec["value"] == 214.5  # PREDICT_VALUE "214.5" -> float


def test_non_game_line_is_dropped():
    # The Team Future has no PREDICT_MARKET_TYPE == "Game Line".
    assert to_selection_record(FUT_FLAT) is None


def test_securitydef_record_parses_as_mapper_input():
    sel = parse_selection(json.dumps(SPREAD_DEF_FLAT))
    assert sel is not None
    assert sel.security_id == "SP-001"
    assert sel.value == 3.5


def test_full_records_parse_as_mapper_input():
    # The fetcher's full on-disk record must be valid mapper input.
    # parse_selection consumes the full record directly, returning a
    # Selection for game lines and None for everything else.
    sels = [parse_selection(json.dumps(flat)) for flat in (ML_FLAT, TP_FLAT, FUT_FLAT)]
    assert sels[0] is not None and sels[0].security_id == "ML-001"
    assert sels[1] is not None and sels[1].value == 214.5
    assert sels[2] is None  # the Team Future is skipped on read


# === Underlying-securities player-prop supplement ===

# A raw game-line contract (carries the team/game identity) and an
# underlying-securities prop row for the SAME fixture (shares the symbol
# prefix NX.F.OPT.FIFA-00001-260626 but carries no team/game IDs).
RAW_GAME_LINE = {
    "Symbol": "NX.F.OPT.FIFA-00001-260626-M.O.1.1",
    "SecurityID": "GL-001",
    "eventMetaEXTERNAL_HOME_ID": "30000001",
    "eventMetaEXTERNAL_AWAY_ID": "30000002",
    "eventMetaEXTERNAL_GAME_ID": "90099000",
    "eventMetaHOME_PARTICIPANT": "Norway",
    "eventMetaAWAY_PARTICIPANT": "France",
}


def _prop(symbol, security_id, contract_type="Anytime Goal Scorer", participant="Kylian Mbappe", meta_name=None):
    return {
        "symbol": symbol,
        "security_id": security_id,
        "meta_league": "FIFA",
        "meta_sports_grouping": "SOCCER",
        "meta_event_date": "2026-06-26T19:00:00+00:00",
        "meta_predict_market_type": "Player Prop",
        "meta_predict_contract_type": contract_type,
        "meta_predict_period_type": "90 Minutes and Stoppage Time",
        "meta_predict_event_type": "Player",
        "meta_event_name": f"{participant} {contract_type}",
        "meta_name": meta_name,
        "meta_predict_market_id": "MKT-P",
        "meta_predict_outcome_id": "OUT-P",
        "meta_participant": participant,
        "publish_time": "2026-06-24T16:09:12+00:00",
    }


def test_build_identity_index_keys_on_symbol_prefix():
    index = build_identity_index([RAW_GAME_LINE])
    assert set(index) == {"NX.F.OPT.FIFA-00001-260626"}
    identity = index["NX.F.OPT.FIFA-00001-260626"]
    assert identity["eventMetaEXTERNAL_HOME_ID"] == "30000001"
    assert identity["eventMetaEXTERNAL_GAME_ID"] == "90099000"


def test_build_identity_index_skips_contracts_without_ids():
    # A combo (too-short symbol) and an id-less contract contribute nothing.
    combo = {"Symbol": "NX.F.OPT.COMBOS-20260423.O.3021965.1", "SecurityID": "C-1"}
    idless = {"Symbol": "NX.F.OPT.FIFA-00009-260626-M.O.1.1", "SecurityID": "X-1"}
    assert build_identity_index([combo, idless]) == {}


def test_synthesize_prop_records_bridges_identity_and_parses():
    index = build_identity_index([RAW_GAME_LINE])
    prop = _prop("NX.F.OPT.FIFA-00001-260626-M.O.2.64.20260830", "PROP-064")
    records, skipped = synthesize_prop_records([prop], index, {"GL-001"})
    assert skipped == 0
    assert len(records) == 1
    rec = records[0]
    # Fixture identity bridged from the raw game line.
    assert rec["eventMetaEXTERNAL_HOME_ID"] == "30000001"
    assert rec["eventMetaEXTERNAL_GAME_ID"] == "90099000"
    # No PLAYER_ID available from this source.
    assert rec["eventMetaPLAYER_ID"] is None
    # And the synthesized record is valid mapper input as a player prop.
    sel = parse_selection(json.dumps(rec))
    assert sel is not None
    assert sel.market_group == "Player Prop"
    assert sel.participant == "Kylian Mbappe"
    assert sel.player_id is None


def test_synthesize_prop_records_skips_unbridgeable_and_duplicate():
    index = build_identity_index([RAW_GAME_LINE])
    # One prop for a fixture with no identity, one already-present SecurityID.
    no_fixture = _prop("NX.F.OPT.FIFA-00077-260626-M.O.2.64.20260830", "PROP-x")
    dup = _prop("NX.F.OPT.FIFA-00001-260626-M.O.2.65.20260830", "GL-001")
    records, skipped = synthesize_prop_records([no_fixture, dup], index, {"GL-001"})
    assert records == []
    assert skipped == 1  # only the no-identity prop counts as skipped


def test_fetch_underlying_props_missing_table_returns_empty():
    client = MagicMock()
    with patch(
        "fetch.crypto_com_underlying.ro_query",
        side_effect=NotFound("Table rs-marketmaking:processed_upstream_us.crypto_underlying_securities was not found"),
    ):
        assert fetch_underlying_props(client, 60) == []


# === Underlying-securities full catalogue (game lines + props) ===


def _game_line_row(
    symbol_suffix: str,
    *,
    contract_type: str = "Moneyline (3-Way)",
    participant: str | None = "Argentina",
    event_name: str = "Argentina to win",
    security_id: str = "GL-ARG",
    outcome_type: str | None = "Home",
):
    return {
        "symbol": f"NX.F.OPT.FIFA-00001-260703-M.O.1.{symbol_suffix}",
        "security_id": security_id,
        "meta_league": "FIFA",
        "meta_sports_grouping": "SOCCER",
        "meta_event_date": "2026-07-03T19:00:00+00:00",
        "meta_predict_market_type": "Game Line",
        "meta_predict_contract_type": contract_type,
        "meta_predict_period_type": "90 Minutes and Stoppage Time",
        "meta_predict_event_type": "Team",
        "meta_event_name": event_name,
        "meta_name": "Cabo Verde @ Argentina",
        "meta_predict_market_id": "MKT-ML",
        "meta_predict_outcome_id": "OUT-ML",
        "meta_participant": participant,
        "meta_predict_outcome_type": outcome_type,
        "security_desc": "Argentina vs Cabo Verde ; Argentina to win",
        "publish_time": "2026-06-30T15:02:00+00:00",
    }


def _typed_line(contract_type, outcome_type, value=None, **extra):
    return {
        "meta_predict_contract_type": contract_type,
        "meta_predict_outcome_type": outcome_type,
        "meta_predict_value": value,
        **extra,
    }


def test_infer_game_line_reads_typed_outcome_and_value():
    assert infer_game_line_outcome(_typed_line("Moneyline", "Home")) == ("Home", None)
    assert infer_game_line_outcome(_typed_line("Moneyline (3-Way)", "Draw")) == ("Draw", None)
    assert infer_game_line_outcome(_typed_line("Total Runs", "Over", "8.5")) == ("Over", 8.5)
    assert infer_game_line_outcome(_typed_line("Spread", "Away", "-13.5")) == ("Away", -13.5)


def test_infer_spread_positive_handicap_ignores_display_text():
    """Real NFL row (Seahawks @ Broncos, 2026-10-16): the event name drops the
    "+" and security_desc uses a period-prefixed short name.  Neither is read;
    the typed PREDICT_VALUE is already signed."""
    row = _typed_line(
        "Spread", "Away", "24.5",
        meta_event_name="Seattle Seahawks 24.5 to win",
        security_desc="Seahawks vs Broncos ; 1st Half Seahawks +24.5 ; Empower Field at Mile High ; 261015",
    )
    assert infer_game_line_outcome(row) == ("Away", 24.5)


def test_infer_game_line_without_typed_fields_is_unparsed():
    """No typed outcome/value -> (None, None) so the fetch alerts on the row;
    the line is never guessed from security_desc."""
    assert infer_game_line_outcome(
        {
            "meta_predict_contract_type": "Spread",
            "meta_event_name": "England -3.5 to win",
            "security_desc": "England vs Argentina ; England -3.5 ; Wembley ; 260715",
        }
    ) == (None, None)
    assert infer_game_line_outcome(_typed_line("Spread", "Home", None)) == (None, None)
    assert infer_game_line_outcome(_typed_line("Total Goals", "Over", "n/a")) == (None, None)


def test_infer_player_prop_over_under_from_security_desc():
    line, side = infer_player_prop_line_side(
        "Orioles vs Tigers ; Tarik Skubal Total Pitching Strikeouts Over 8.5 ; 260729",
    )
    assert (line, side) == (8.5, "Over")

    line, side = infer_player_prop_line_side(
        "Orioles vs Tigers ; Tarik Skubal Total Pitching Strikeouts Under 8.5 ; 260729",
    )
    assert (line, side) == (8.5, "Under")


def test_infer_player_prop_milestone_n_plus():
    line, side = infer_player_prop_line_side(
        "Brewers vs Giants ; Heliot Ramos Total Hits Milestone 1+ ; 260729",
    )
    assert (line, side) == (0.5, "Over")

    line, side = infer_player_prop_line_side(
        "Orioles vs Tigers ; Christian Encarnacion-Strand Total Bases Milestone 3+ ; 260729",
    )
    assert (line, side) == (2.5, "Over")


def test_infer_player_prop_yes_no_has_no_numeric_line():
    line, side = infer_player_prop_line_side(
        "Brewers vs Giants ; Heliot Ramos To Get A Hit ; 260729",
    )
    assert (line, side) == (None, None)


def test_security_def_recovers_player_prop_line():
    row = SimpleNamespace(
        publish_time=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        security_id="SID-PROP-1",
        symbol="NX.F.OPT.MLB-00004-260729-M.O.1.100.20261130",
        security_desc=("Orioles vs Tigers ; Tarik Skubal Total Pitching Strikeouts Over 8.5 ; 260729"),
        security_type=None,
        security_sub_type=None,
        currency=None,
        strike_price=None,
        min_price_increment=None,
        maturity_date=None,
        product=None,
        security_req_id=None,
        event_code=None,
        event_name=None,
        attributes=None,
        meta_league="MLB",
        meta_name="Baltimore Orioles @ Detroit Tigers",
        meta_sports_grouping="MLB",
        meta_event_date="2026-07-29T17:10:00+00:00",
        meta_home_participant="Detroit Tigers",
        meta_away_participant="Baltimore Orioles",
        meta_external_home_id="10000012",
        meta_external_away_id="10000005",
        meta_external_game_id="10078905",
        meta_external_tournament_id=None,
        meta_participant="Tarik Skubal",
        meta_player_id="10010729",
        meta_predict_market_type="Player Prop",
        meta_predict_contract_type="Total Pitching Strikeouts",
        meta_predict_period_type="Full-Game",
        meta_predict_event_type=None,
        meta_predict_category=None,
        meta_predict_market_id="MID",
        meta_predict_outcome_id="OID",
        meta_predict_outcome_type="Over",
        meta_venue=None,
        meta_feed_type=None,
        meta_alpha_strike=None,
        meta_version=None,
    )
    flat = security_def_row_to_flat(row)
    assert flat is not None
    assert flat["eventMetaPREDICT_VALUE"] == "8.5"
    assert flat["eventMetaPREDICT_OUTCOME_TYPE"] == "Over"


def _seed_identity(
    prefix: str,
    *,
    home_id: str,
    away_id: str,
    home_name: str,
    away_name: str,
) -> dict[str, dict]:
    """security_def-style identity seed for one fixture prefix."""
    return {
        prefix: {
            "eventMetaEXTERNAL_HOME_ID": home_id,
            "eventMetaEXTERNAL_AWAY_ID": away_id,
            "eventMetaEXTERNAL_GAME_ID": prefix,
            "eventMetaHOME_PARTICIPANT": home_name,
            "eventMetaAWAY_PARTICIPANT": away_name,
        },
    }


def test_synthesize_catalogue_records_requires_security_def_seed():
    """Without EXTERNAL_* seed, game lines and bridged props are dropped."""
    rows = [
        _game_line_row("1", participant="Argentina", event_name="Argentina to win"),
        _prop(
            "NX.F.OPT.FIFA-00001-260703-M.O.2.69.20260830",
            "PROP-069",
            contract_type="Anytime Goal Scorer",
            participant="Lionel Messi",
        ),
    ]
    records, stats = synthesize_catalogue_records(rows, {}, set())
    assert records == []
    assert stats.skipped_no_identity == 2
    assert stats.no_identity_prefixes == ("NX.F.OPT.FIFA-00001-260703",)


def test_synthesize_catalogue_records_with_security_def_seed():
    """Seeded EXTERNAL_* identity stamps game lines and bridges props."""
    rows = [
        _game_line_row("1", participant="Argentina", event_name="Argentina to win"),
        _prop(
            "NX.F.OPT.FIFA-00001-260703-M.O.2.69.20260830",
            "PROP-069",
            contract_type="Anytime Goal Scorer",
            participant="Lionel Messi",
        ),
    ]
    seed = _seed_identity(
        "NX.F.OPT.FIFA-00001-260703",
        home_id="90000859",
        away_id="90001079",
        home_name="Argentina",
        away_name="Cabo Verde",
    )
    records, stats = synthesize_catalogue_records(rows, seed, set())
    assert stats.game_lines == 1
    assert stats.player_props == 1
    assert stats.skipped_no_identity == 0
    assert len(records) == 2
    ml = next(r for r in records if r["SecurityID"] == "GL-ARG")
    assert ml["eventMetaEXTERNAL_HOME_ID"] == "90000859"
    assert ml["eventMetaEXTERNAL_AWAY_ID"] == "90001079"
    assert ml["eventMetaPREDICT_OUTCOME_TYPE"] == "Home"
    sel = parse_selection(json.dumps(ml))
    assert sel is not None
    assert sel.outcome_type == "Home"
    prop = next(r for r in records if r["SecurityID"] == "PROP-069")
    prop_sel = parse_selection(json.dumps(prop))
    assert prop_sel is not None
    assert prop_sel.participant == "Lionel Messi"


def test_publish_missing_seed_alert_on_drops():
    """Missing-seed drops publish one warning; empty stats suppress publish."""
    from fetch.crypto_com_underlying import (
        format_missing_seed_alert,
        publish_missing_seed_alert,
    )

    empty = UnderlyingStats()
    assert format_missing_seed_alert(empty) is None

    dropped = UnderlyingStats(
        skipped_no_identity=2,
        no_identity_prefixes=("NX.F.OPT.FIFA-00001-260703",),
    )
    text = format_missing_seed_alert(dropped)
    assert text is not None
    assert "no usable security_def identity" in text
    assert "NX.F.OPT.FIFA-00001-260703" in text

    publisher = MagicMock()
    with patch(
        "fetch.crypto_com_underlying.build_publisher",
        return_value=publisher,
    ):
        publish_missing_seed_alert(dropped)
    publisher.publish.assert_called_once_with("warning", text)
    publisher.close.assert_called_once()

    with patch(
        "fetch.crypto_com_underlying.build_publisher",
        return_value=publisher,
    ) as build:
        publish_missing_seed_alert(empty)
    build.assert_not_called()


def test_synthesize_catalogue_records_fight_line_and_prop():
    """UFC Fight Line/Prop rows must be fetched and flattened like Game Line/Prop."""
    rows = [
        {
            "symbol": "NX.F.OPT.UFC-00013-260725-M.O.1.1.20261231",
            "security_id": "FL-GIB",
            "meta_league": "UFC",
            "meta_sports_grouping": "MMA",
            "meta_event_date": "2026-07-25T13:15:00+00:00",
            "meta_predict_market_type": "Fight Line",
            "meta_predict_contract_type": "Moneyline",
            "meta_predict_period_type": "Full Fight",
            "meta_predict_event_type": "Team",
            "meta_event_name": "Cody Gibson to win",
            "meta_name": "Cody Gibson vs Abdul Hussein",
            "meta_predict_market_id": "MKT-ML",
            "meta_predict_outcome_id": "OUT-ML",
            "meta_participant": "Cody Gibson",
            "meta_predict_outcome_type": "Home",
            "security_desc": "Cody Gibson vs Abdul Hussein ; Cody Gibson to win",
            "publish_time": "2026-07-23T15:02:00+00:00",
        },
        {
            "symbol": "NX.F.OPT.UFC-00013-260725-M.O.3.25.20261231",
            "security_id": "FP-SUB",
            "meta_league": "UFC",
            "meta_sports_grouping": "MMA",
            "meta_event_date": "2026-07-25T13:15:00+00:00",
            "meta_predict_market_type": "Fight Prop",
            "meta_predict_contract_type": "Method of Victory",
            "meta_predict_period_type": "Full Fight",
            "meta_predict_event_type": "Event",
            "meta_event_name": "Cody Gibson by Submission",
            "meta_name": "Cody Gibson vs Abdul Hussein: Method of Victory",
            "meta_predict_market_id": "MKT-MOV",
            "meta_predict_outcome_id": "OUT-MOV",
            "meta_participant": "Cody Gibson by Submission",
            "security_desc": ("Cody Gibson vs Abdul Hussein ; Cody Gibson by Submission"),
            "publish_time": "2026-07-23T15:02:00+00:00",
        },
    ]
    seed = _seed_identity(
        "NX.F.OPT.UFC-00013-260725",
        home_id="140002905",
        away_id="140005773",
        home_name="Cody Gibson",
        away_name="Abdul Hussein",
    )
    records, stats = synthesize_catalogue_records(rows, seed, set())
    assert stats.game_lines == 1
    assert stats.game_props == 1
    assert len(records) == 2
    ml = next(r for r in records if r["SecurityID"] == "FL-GIB")
    assert ml["eventMetaPREDICT_MARKET_TYPE"] == "Fight Line"
    assert ml["eventMetaPREDICT_OUTCOME_TYPE"] == "Home"
    prop = next(r for r in records if r["SecurityID"] == "FP-SUB")
    assert prop["eventMetaPREDICT_MARKET_TYPE"] == "Fight Prop"
    assert prop["eventMetaPREDICT_OUTCOME_TYPE"] == "Yes"


def test_team_id_from_participant_matches_short_and_suffix_names():
    assert team_id_from_participant(
        "Giants", "Dallas Cowboys", "New York Giants", "dal-id", "nyg-id",
    ) == "nyg-id"
    assert team_id_from_participant(
        "San Jose State", "Cal Poly Mustangs", "San Jose State Spartans",
        "cp-id", "sjs-id",
    ) == "sjs-id"
    assert team_id_from_participant(
        "giants", "Dallas Cowboys", "New York Giants", "dal-id", "nyg-id",
    ) == "nyg-id"


def test_team_id_from_participant_rejects_ambiguous_and_prefix_false_bind():
    assert team_id_from_participant(
        "New York", "New York Jets", "New York Giants", "nyj-id", "nyg-id",
    ) is None
    assert team_id_from_participant(
        "Ohio", "Ohio State Buckeyes", "Michigan Wolverines", "osu-id", "mich-id",
    ) is None


def test_synthesize_team_prop_total_points():
    rows = [{
        "symbol": "NX.F.OPT.NFL-00013-260913-M.O.1.222",
        "security_id": "NFL-TT-NYG",
        "meta_league": "NFL",
        "meta_sports_grouping": "NFL",
        "meta_event_date": "2026-09-13T17:00:00+00:00",
        "meta_predict_market_type": "Team Prop",
        "meta_predict_contract_type": "Total Points",
        "meta_predict_period_type": "Full-Game",
        "meta_predict_event_type": "Game",
        "meta_event_name": "New York Giants Over 22.5 Total Points",
        "meta_name": "Dallas Cowboys @ New York Giants",
        "meta_predict_market_id": "MKT-TT",
        "meta_predict_outcome_id": "OUT-TT",
        "meta_participant": "Giants",
        "security_desc": "Cowboys vs Giants ; Giants Total Points Over 22.5 ; MetLife",
        "publish_time": "2026-09-10T12:00:00+00:00",
    }]
    seed = _seed_identity(
        "NX.F.OPT.NFL-00013-260913",
        home_id="dal-id",
        away_id="nyg-id",
        home_name="Dallas Cowboys",
        away_name="New York Giants",
    )
    records, stats = synthesize_catalogue_records(rows, seed, set())
    assert stats.team_props == 1
    assert stats.game_props == 0
    assert len(records) == 1
    rec = records[0]
    assert rec["eventMetaPREDICT_MARKET_TYPE"] == "Team Prop"
    assert rec["eventMetaPREDICT_OUTCOME_TYPE"] == "Over"
    assert rec["eventMetaPREDICT_VALUE"] == 22.5
    assert rec["eventMetaTEAM_ID"] == "nyg-id"


def test_synthesize_flags_unparsed_game_line(caplog):
    """A resolved fixture whose outcome cannot be inferred (here an unhandled
    contract type) is counted as a game-line mapping gap and logged at
    WARNING — never silently folded into the benign 'no identity' bucket."""
    rows = [
        _game_line_row(
            "7",
            contract_type="Double Chance",  # not handled by the inferrer
            participant=None,
            event_name="Argentina or draw",
            security_id="GL-DC",
            outcome_type=None,
        ),
    ]
    seed = _seed_identity(
        "NX.F.OPT.FIFA-00001-260703",
        home_id="90000859",
        away_id="90001079",
        home_name="Argentina",
        away_name="Cabo Verde",
    )
    with caplog.at_level(logging.WARNING):
        records, stats = synthesize_catalogue_records(rows, seed, set())

    assert records == []
    assert stats.skipped_unparsed_game_line == 1
    assert stats.skipped_no_identity == 0
    assert stats.game_lines == 0
    messages = [r.getMessage() for r in caplog.records]
    assert any("game-line mapping gap" in m for m in messages)
    assert any("Double Chance" in m for m in messages)


def test_synthesize_no_identity_distinct_from_unparsed(caplog):
    """A row whose fixture is not seeded is still 'no identity', kept
    separate from the unparsed-outcome gap and not alerted as a mapper bug."""
    rows = [_game_line_row("1", participant="Argentina", event_name="Argentina to win")]
    with caplog.at_level(logging.WARNING):
        records, stats = synthesize_catalogue_records(rows, {}, set())

    assert records == []
    assert stats.skipped_no_identity == 1
    assert stats.skipped_unparsed_game_line == 0
    assert stats.no_identity_prefixes == ("NX.F.OPT.FIFA-00001-260703",)
    assert not any("game-line mapping gap" in r.getMessage() for r in caplog.records)


def test_synthesize_catalogue_records_to_advance_team_id():
    """To Advance from underlying must carry TEAM_ID for build_rows."""
    rows = [
        {
            "symbol": "NX.F.OPT.FIFA-00002-260628-M.O.1.1",
            "security_id": "202606272345329001764175D",
            "meta_league": "FIFA",
            "meta_sports_grouping": "SOCCER",
            "meta_event_date": "2026-06-28T19:00:00+00:00",
            "meta_predict_market_type": "Game Line",
            "meta_predict_contract_type": "To Advance",
            "meta_predict_period_type": "Full Game",
            "meta_predict_event_type": "Team",
            "meta_event_name": "South Africa to advance",
            "meta_name": "South Africa @ Canada",
            "meta_predict_market_id": "MKT-ADV",
            "meta_predict_outcome_id": "OUT-ADV",
            "meta_participant": "South Africa",
            "meta_predict_outcome_type": "Away",
            "security_desc": "Canada vs South Africa ; South Africa to advance",
            "publish_time": "2026-06-28T12:00:00+00:00",
        },
    ]
    seed = _seed_identity(
        "NX.F.OPT.FIFA-00002-260628",
        home_id="90000966",
        away_id="90001083",
        home_name="Canada",
        away_name="South Africa",
    )
    records, stats = synthesize_catalogue_records(rows, seed, set())
    assert stats.game_lines == 1
    rec = records[0]
    assert rec["eventMetaTEAM_ID"] == "90001083"
    assert rec["eventMetaPREDICT_OUTCOME_TYPE"] == "Away"
    sel = parse_selection(json.dumps(rec))
    assert sel is not None
    aliases = {"90000966": "CAN", "90001083": "RSA"}
    rows_out = build_rows(
        "2026-06-28T19:00:00+00:00",
        "CAN",
        "RSA",
        [sel],
        SOCCER_CRYPTO,
        aliases=aliases,
        league="world_cup",
    )
    assert len(rows_out) == 1


def test_synthesize_catalogue_records_to_lift_the_cup():
    """Final 'To Lift The Cup' legs synthesize and map as to_advance."""
    rows = [
        {
            "symbol": "NX.F.OPT.FIFA-00001-260719-M.O.2.1.20260831",
            "security_id": "202607151846204701314461D",
            "meta_league": "FIFA",
            "meta_sports_grouping": "SOCCER",
            "meta_event_date": "2026-07-19T19:00:00+00:00",
            "meta_predict_market_type": "Game Line",
            "meta_predict_contract_type": "To Lift The Cup",
            "meta_predict_period_type": "Full Game",
            "meta_predict_event_type": "Team",
            "meta_event_name": "Argentina to win",
            "meta_name": "Argentina @ Spain",
            "meta_predict_market_id": "MKT-CUP",
            "meta_predict_outcome_id": "OUT-CUP",
            "meta_participant": "Argentina",
            "meta_predict_outcome_type": "Away",
            "security_desc": ("Spain vs Argentina ; Argentina To Lift The Cup ; MetLife Stadium ; 260719"),
            "publish_time": "2026-07-16T08:28:35+00:00",
        },
    ]
    seed = _seed_identity(
        "NX.F.OPT.FIFA-00001-260719",
        home_id="90000958",
        away_id="90000859",
        home_name="Spain",
        away_name="Argentina",
    )
    records, stats = synthesize_catalogue_records(rows, seed, set())
    assert stats.game_lines == 1
    assert stats.skipped_unparsed_game_line == 0
    rec = records[0]
    assert rec["eventMetaTEAM_ID"] == "90000859"
    assert rec["eventMetaPREDICT_OUTCOME_TYPE"] == "Away"
    sel = parse_selection(json.dumps(rec))
    assert sel is not None
    aliases = {"90000859": "ARG", "90000958": "ESP"}
    built = build_rows(
        "2026-07-19T19:00:00+00:00",
        "ESP",
        "ARG",
        [sel],
        SOCCER_CRYPTO,
        aliases=aliases,
        league="world_cup",
    )
    assert len(built) == 1
    assert built[0].market_type == "to_advance"
    assert built[0].entity == "ARG"
    assert built[0].side == "yes"


def test_synthesize_catalogue_records_to_win_bronze():
    """Bronze 'To Win Bronze' legs synthesize and map as to_advance."""
    rows = [
        {
            "symbol": "NX.F.OPT.FIFA-00001-260718-M.O.3.1.20260831",
            "security_id": "202607161655000000000001D",
            "meta_league": "FIFA",
            "meta_sports_grouping": "SOCCER",
            "meta_event_date": "2026-07-18T21:00:00+00:00",
            "meta_predict_market_type": "Game Line",
            "meta_predict_contract_type": "To Win Bronze",
            "meta_predict_period_type": "Full Game",
            "meta_predict_event_type": "Team",
            "meta_event_name": "England to win",
            "meta_name": "England @ France",
            "meta_predict_market_id": "MKT-BRZ",
            "meta_predict_outcome_id": "OUT-BRZ",
            "meta_participant": "England",
            "meta_predict_outcome_type": "Away",
            "security_desc": ("France vs England ; England To Win Bronze ; Hard Rock Stadium ; 90000858"),
            "publish_time": "2026-07-16T16:55:41+00:00",
        },
    ]
    seed = _seed_identity(
        "NX.F.OPT.FIFA-00001-260718",
        home_id="90000946",
        away_id="90000858",
        home_name="France",
        away_name="England",
    )
    records, stats = synthesize_catalogue_records(rows, seed, set())
    assert stats.game_lines == 1
    assert stats.skipped_unparsed_game_line == 0
    rec = records[0]
    assert rec["eventMetaTEAM_ID"] == "90000858"
    assert rec["eventMetaPREDICT_OUTCOME_TYPE"] == "Away"
    sel = parse_selection(json.dumps(rec))
    assert sel is not None
    aliases = {"90000858": "ENG", "90000946": "FRA"}
    built = build_rows(
        "2026-07-18T21:00:00+00:00",
        "FRA",
        "ENG",
        [sel],
        SOCCER_CRYPTO,
        aliases=aliases,
        league="world_cup",
    )
    assert len(built) == 1
    assert built[0].market_type == "to_advance"
    assert built[0].entity == "ENG"
    assert built[0].side == "yes"


def test_security_def_row_to_flat_parses_attributes():
    attrs = json.dumps(
        {
            "eventCode": "202606290933317601351378D",
            "eventName": "Enrico Dalla Valle to win",
            "eventMetadata": [
                {"eventPropertyTypeCode": "LEAGUE", "eventPropertyValue": "ATP"},
                {"eventPropertyTypeCode": "PREDICT_MARKET_TYPE", "eventPropertyValue": "Game Line"},
                {"eventPropertyTypeCode": "PREDICT_CONTRACT_TYPE", "eventPropertyValue": "Moneyline"},
                {"eventPropertyTypeCode": "PREDICT_OUTCOME_TYPE", "eventPropertyValue": "Home"},
                {"eventPropertyTypeCode": "EXTERNAL_GAME_ID", "eventPropertyValue": "5859066"},
            ],
        }
    )
    row = SimpleNamespace(
        security_id="202606290933317601351378D",
        symbol="NX.F.OPT.TENNIS-0024-260630-M.O.1.2.20261231",
        security_desc="Enrico Dalla Valle to win",
        security_type="OPT",
        security_sub_type="BINARY_OPTION",
        currency="USD",
        strike_price=1.0,
        min_price_increment=0.01,
        maturity_date="20261231",
        product="102",
        security_req_id="seclist_123",
        event_code="202606290933317601351378D",
        event_name="Enrico Dalla Valle to win",
        attributes=attrs,
    )
    flat = security_def_row_to_flat(row)
    assert flat is not None
    assert flat["SecurityID"] == "202606290933317601351378D"
    assert flat["eventMetaLEAGUE"] == "ATP"
    assert flat["eventMetaPREDICT_MARKET_TYPE"] == "Game Line"
    assert flat["eventMetaPREDICT_CONTRACT_TYPE"] == "Moneyline"


def test_security_def_row_to_flat_uses_meta_columns():
    """New-style rows carry flattened meta_* columns and null attributes."""
    row = SimpleNamespace(
        security_id="SD-UCL-1",
        symbol="NX.F.OPT.UCL-00002-260716-M.O.1.1.20261231",
        security_desc="FC Flora Tallinn vs FC Iberia 1999",
        security_type="OPT",
        security_sub_type="BINARY_OPTION",
        currency="USD",
        strike_price=1.0,
        min_price_increment=0.01,
        maturity_date="20261231",
        product="102",
        security_req_id="seclist_1",
        event_code="evt-1",
        event_name="FC Flora Tallinn to win",
        attributes=None,  # columns are the only source now
        meta_league="UCL",
        meta_sports_grouping="SOCCER",
        meta_event_date="2026-07-16T19:00:00+00:00",
        meta_predict_market_type="Game Line",
        meta_predict_contract_type="Moneyline",
        meta_predict_period_type="90 Minutes and Stoppage Time",
        meta_predict_outcome_type="Home",
        meta_predict_market_id="MKT-1",
        meta_predict_outcome_id="OUT-1",
        meta_home_participant="FC Flora Tallinn",
        meta_away_participant="FC Iberia 1999",
        meta_external_home_id="700001",
        meta_external_away_id="700002",
        meta_external_game_id="90099123",
    )
    flat = security_def_row_to_flat(row)
    assert flat is not None
    assert flat["eventMetaLEAGUE"] == "UCL"
    assert flat["eventMetaPREDICT_MARKET_TYPE"] == "Game Line"
    assert flat["eventMetaEXTERNAL_HOME_ID"] == "700001"
    assert flat["eventMetaEXTERNAL_AWAY_ID"] == "700002"
    assert flat["eventMetaEXTERNAL_GAME_ID"] == "90099123"
    assert flat["eventMetaHOME_PARTICIPANT"] == "FC Flora Tallinn"
    # Valid mapper input even though attributes JSON is null.
    sel = parse_selection(json.dumps(flat))
    assert sel is not None
    assert sel.external_home_id == "700001"


def test_security_def_spread_reads_typed_signed_value():
    """The signed handicap comes from the typed meta_predict_value column;
    the sign-dropping event name and security_desc are not read."""
    row = SimpleNamespace(
        security_id="SD-FIFA-SPR-A",
        symbol="NX.F.OPT.FIFA-00001-260714-M.O.1.10.20260830",
        security_desc="France vs Spain ; Spain +4.5 ; AT&T Stadium ; 260714",
        security_type="OPT",
        security_sub_type="BINARY_OPTION",
        currency="USD",
        strike_price=1.0,
        min_price_increment=0.01,
        maturity_date="20260830",
        product="102",
        security_req_id="seclist_1",
        event_code="evt-spr",
        event_name="Spain 4.5 to win",  # sign dropped
        attributes=None,
        meta_league="FIFA",
        meta_sports_grouping="SOCCER",
        meta_event_date="2026-07-14T19:00:00+00:00",
        meta_predict_market_type="Game Line",
        meta_predict_contract_type="Spread",
        meta_predict_period_type="90 Minutes and Stoppage Time",
        meta_predict_outcome_type="Away",
        meta_predict_value="4.5",
        meta_predict_market_id="MKT-SPR",
        meta_predict_outcome_id="OUT-SPR",
        meta_home_participant="France",
        meta_away_participant="Spain",
        meta_external_home_id="90000001",
        meta_external_away_id="90000002",
        meta_external_game_id="90099999",
    )
    flat = security_def_row_to_flat(row)
    assert flat is not None
    assert flat["eventMetaPREDICT_VALUE"] == "4.5"  # +4.5 for the Away leg
    sel = parse_selection(json.dumps(flat))
    assert sel is not None
    assert sel.value == 4.5


def test_security_def_total_reads_typed_threshold():
    """A total's threshold comes from the typed meta_predict_value column."""
    row = SimpleNamespace(
        security_id="SD-MLB-TOT-O",
        symbol="NX.F.OPT.MLB-00001-260714-M.O.2.1.20260831",
        security_desc="AL Stars vs NL Stars ; Over 4.5 ; Citizens Bank ; 260714",
        security_type="OPT",
        security_sub_type="BINARY_OPTION",
        currency="USD",
        strike_price=1.0,
        min_price_increment=0.01,
        maturity_date="20260831",
        product="102",
        security_req_id="seclist_2",
        event_code="evt-tot",
        event_name="Over 4.5 to win",
        attributes=None,
        meta_league="MLB",
        meta_sports_grouping="MLB",
        meta_event_date="2026-07-14T23:10:00+00:00",
        meta_predict_market_type="Game Line",
        meta_predict_contract_type="Total Runs",
        meta_predict_period_type="Full-Game",
        meta_predict_outcome_type="Over",
        meta_predict_value="4.5",
        meta_predict_market_id="MKT-TOT",
        meta_predict_outcome_id="OUT-TOT",
        meta_home_participant="AL Stars",
        meta_away_participant="NL Stars",
        meta_external_home_id="10000001",
        meta_external_away_id="10000002",
        meta_external_game_id="90088888",
    )
    flat = security_def_row_to_flat(row)
    assert flat is not None
    assert flat["eventMetaPREDICT_VALUE"] == "4.5"


def test_security_def_game_line_without_typed_value_stays_lineless():
    """No typed value -> no line; security_desc is never parsed for game lines."""
    row = SimpleNamespace(
        security_id="SD-FIFA-SPR-B",
        symbol="NX.F.OPT.FIFA-00001-260714-M.O.1.11.20260830",
        security_desc="France vs Spain ; Spain +4.5 ; AT&T Stadium ; 260714",
        event_code="evt-spr",
        event_name="Spain 4.5 to win",
        attributes=None,
        meta_league="FIFA",
        meta_predict_market_type="Game Line",
        meta_predict_contract_type="Spread",
        meta_predict_outcome_type="Away",
    )
    flat = security_def_row_to_flat(row)
    assert flat is not None
    assert "eventMetaPREDICT_VALUE" not in flat


def test_security_def_moneyline_recovers_no_line():
    """Moneyline carries no threshold; recovery must not invent one."""
    row = SimpleNamespace(
        security_id="SD-UCL-ML",
        symbol="NX.F.OPT.UCL-00002-260716-M.O.1.1.20261231",
        security_desc="Flora vs Iberia ; Flora ; Tallinn ; 260716",
        security_type="OPT",
        security_sub_type="BINARY_OPTION",
        currency="USD",
        strike_price=1.0,
        min_price_increment=0.01,
        maturity_date="20261231",
        product="102",
        security_req_id="seclist_3",
        event_code="evt-ml",
        event_name="Flora to win",
        attributes=None,
        meta_league="UCL",
        meta_sports_grouping="SOCCER",
        meta_event_date="2026-07-16T19:00:00+00:00",
        meta_predict_market_type="Game Line",
        meta_predict_contract_type="Moneyline",
        meta_predict_period_type="90 Minutes and Stoppage Time",
        meta_predict_outcome_type="Home",
        meta_predict_market_id="MKT-1",
        meta_predict_outcome_id="OUT-1",
        meta_home_participant="Flora",
        meta_away_participant="Iberia",
        meta_external_home_id="700001",
        meta_external_away_id="700002",
        meta_external_game_id="90099123",
    )
    flat = security_def_row_to_flat(row)
    assert flat is not None
    assert flat.get("eventMetaPREDICT_VALUE") is None


def test_underlying_inherits_security_def_identity():
    """Underlying rows inherit EXTERNAL ids seeded from security_def.

    No alias entry exists for the teams, so only the security_def-derived
    seed index can supply fixture identity (the Flora/Iberia gap class).
    """
    sd_contract = {
        "Symbol": "NX.F.OPT.UCL-00002-260716-M.O.1.1",
        "SecurityID": "SD-GL",
        "eventMetaEXTERNAL_HOME_ID": "700001",
        "eventMetaEXTERNAL_AWAY_ID": "700002",
        "eventMetaEXTERNAL_GAME_ID": "90099123",
        "eventMetaHOME_PARTICIPANT": "FC Flora Tallinn",
        "eventMetaAWAY_PARTICIPANT": "FC Iberia 1999",
    }
    seed = build_identity_index([sd_contract])
    prop = {
        "symbol": "NX.F.OPT.UCL-00002-260716-M.O.2.10.20260830",
        "security_id": "PROP-UCL",
        "meta_league": "UCL",
        "meta_sports_grouping": "SOCCER",
        "meta_event_date": "2026-07-16T19:00:00+00:00",
        "meta_predict_market_type": "Player Prop",
        "meta_predict_contract_type": "Anytime Goal Scorer",
        "meta_predict_period_type": "90 Minutes and Stoppage Time",
        "meta_predict_event_type": "Player",
        "meta_event_name": "Someone to score",
        "meta_name": None,
        "meta_predict_market_id": "MKT",
        "meta_predict_outcome_id": "OUT",
        "meta_participant": "Some Player",
        "security_desc": None,
        "publish_time": "2026-07-14T00:00:00+00:00",
    }
    records, stats = synthesize_catalogue_records([prop], seed, set())
    assert stats.player_props == 1
    assert len(records) == 1
    assert records[0]["eventMetaEXTERNAL_HOME_ID"] == "700001"
    assert records[0]["eventMetaEXTERNAL_GAME_ID"] == "90099123"


def test_underlying_moneyline_side_follows_identity_not_meta_name_order():
    """A fixture's home/away must come from the resolved identity, not a
    per-row re-guess of meta_name word order.

    Regression for the 2026-08-01 Rakic/Tybura swap: crypto.com's own
    security_def attributes say Tybura is home (EXTERNAL_HOME_ID/
    HOME_PARTICIPANT), but the underlying catalogue's meta_name for
    Rakic's own selection lists him first ("Aleksandar Rakic vs Marcin
    Tybura ..."). Neither text order nor name matching is used — the
    row's typed PREDICT_OUTCOME_TYPE ("Away") is taken as published.
    """
    sd_contract = {
        "Symbol": "NX.F.OPT.UFC-00003-260801-M.O.1.2.20261231",
        "SecurityID": "SD-TYB",
        "eventMetaEXTERNAL_HOME_ID": "140000272",
        "eventMetaEXTERNAL_AWAY_ID": "140000387",
        "eventMetaEXTERNAL_GAME_ID": "NX.F.OPT.UFC-00003-260801",
        "eventMetaHOME_PARTICIPANT": "Marcin Tybura",
        "eventMetaAWAY_PARTICIPANT": "Aleksandar Rakic",
    }
    seed = build_identity_index([sd_contract])
    rakic_row = {
        "symbol": "NX.F.OPT.UFC-00003-260801-M.O.1.1.20261231",
        "security_id": "UL-RAK",
        "meta_league": "UFC",
        "meta_sports_grouping": "MMA",
        "meta_event_date": "2026-08-01T18:15:00+00:00",
        "meta_predict_market_type": "Fight Line",
        "meta_predict_contract_type": "Moneyline",
        "meta_predict_period_type": "Full Fight",
        "meta_predict_event_type": "Fight",
        "meta_event_name": "Aleksandar Rakic to win",
        "meta_name": "Aleksandar Rakic vs Marcin Tybura (UFC Fight Night: Medic vs. Rodriguez)",
        "meta_predict_market_id": "MKT-ML",
        "meta_predict_outcome_id": "OUT-ML-RAK",
        "meta_participant": "Aleksandar Rakic",
        "meta_predict_outcome_type": "Away",
        "security_desc": None,
        "publish_time": "2026-08-01T00:00:32+00:00",
    }
    records, stats = synthesize_catalogue_records([rakic_row], seed, set())
    assert stats.game_lines == 1
    assert stats.skipped_no_identity == 0
    assert len(records) == 1
    assert records[0]["eventMetaPREDICT_OUTCOME_TYPE"] == "Away"


def test_game_line_drops_when_identity_lacks_participants():
    """IDs without participant names are fail-closed (no text-order name invent)."""
    from fetch.crypto_com_underlying_flat import underlying_row_to_flat

    identity = {
        "eventMetaEXTERNAL_HOME_ID": "90000859",
        "eventMetaEXTERNAL_AWAY_ID": "90001079",
        "eventMetaEXTERNAL_GAME_ID": "NX.F.OPT.FIFA-00001-260703",
        "eventMetaHOME_PARTICIPANT": "",
        "eventMetaAWAY_PARTICIPANT": "",
    }
    row = _game_line_row("1", participant="Argentina", event_name="Argentina to win")
    flat, group, skip = underlying_row_to_flat(row, identity)
    assert flat is None
    assert group is None
    assert skip == "no_identity"


def test_fetch_contracts_primary_underlying_with_security_def_supplement():
    from fetch.crypto_com import fetch_contracts

    t = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)
    with (
        patch("fetch.crypto_com.ro_client", return_value=MagicMock()),
        patch(
            "fetch.crypto_com.fetch_security_def_contracts",
            return_value=([{"SecurityID": "ML-001", "fix_type": "SecurityDef"}], 0, t, 1),
        ),
        patch(
            "fetch.crypto_com.build_catalogue_from_underlying",
            return_value=([], UnderlyingStats(), 0, None),
        ),
    ):
        contracts, source_rows, _, skipped, _, sd_added = fetch_contracts(60)
    assert source_rows == 1
    assert skipped == 0
    assert sd_added == 1
    assert len(contracts) == 1
    assert contracts[0]["SecurityID"] == "ML-001"

    with (
        patch("fetch.crypto_com.ro_client", return_value=MagicMock()),
        patch(
            "fetch.crypto_com.fetch_security_def_contracts",
            return_value=([], 0, None, 0),
        ),
        patch(
            "fetch.crypto_com.build_catalogue_from_underlying",
            return_value=(
                [{"SecurityID": "GL-ARG", "fix_type": "UnderlyingCatalogue"}],
                UnderlyingStats(game_lines=1),
                1,
                None,
            ),
        ),
    ):
        contracts, source_rows, _, skipped, u_stats, sd_added = fetch_contracts(60)
    assert len(contracts) == 1
    assert contracts[0]["SecurityID"] == "GL-ARG"
    assert u_stats.game_lines == 1
    assert sd_added == 0


def test_fetch_contracts_keeps_underlying_when_no_publish_time():
    """Without publish_time to compare, the underlying row stays incumbent."""
    from fetch.crypto_com import fetch_contracts

    primary = [{"SecurityID": "ML-001", "fix_type": "UnderlyingCatalogue"}]
    with (
        patch("fetch.crypto_com.ro_client", return_value=MagicMock()),
        patch(
            "fetch.crypto_com.fetch_security_def_contracts",
            return_value=([{"SecurityID": "ML-001", "fix_type": "SecurityDef"}], 0, None, 1),
        ),
        patch(
            "fetch.crypto_com.build_catalogue_from_underlying",
            return_value=(primary, UnderlyingStats(game_lines=1), 1, None),
        ),
    ):
        contracts, _, _, _, _, sd_added = fetch_contracts(60)
    assert len(contracts) == 1
    assert sd_added == 0
    assert contracts[0]["fix_type"] == "UnderlyingCatalogue"


def test_merge_security_def_refreshes_stale_event_date():
    """Newer SecurityDef publish_time replaces stale underlying EVENT_DATE."""
    underlying = [
        {
            "SecurityID": "TENNIS-ML",
            "publish_time": "2026-07-29T12:00:00+00:00",
            "eventMetaEVENT_DATE": "2026-07-30T09:00:00+00:00",
            "source_type": "UnderlyingCatalogue",
        }
    ]
    security_def = [
        {
            "SecurityID": "TENNIS-ML",
            "publish_time": "2026-07-30T08:00:00+00:00",
            "eventMetaEVENT_DATE": "2026-07-31T09:00:00+00:00",
            "source_type": "SecurityDef",
        }
    ]
    merged, changed = merge_security_def_contracts(underlying, security_def)
    assert changed == 1
    assert len(merged) == 1
    assert merged[0]["eventMetaEVENT_DATE"] == "2026-07-31T09:00:00+00:00"
    assert merged[0]["source_type"] == "SecurityDef"


def test_merge_security_def_keeps_newer_underlying():
    """Older SecurityDef must not overwrite a fresher underlying snapshot."""
    underlying = [
        {
            "SecurityID": "TENNIS-ML",
            "publish_time": "2026-07-30T10:00:00+00:00",
            "eventMetaEVENT_DATE": "2026-07-31T09:00:00+00:00",
        }
    ]
    security_def = [
        {
            "SecurityID": "TENNIS-ML",
            "publish_time": "2026-07-30T08:00:00+00:00",
            "eventMetaEVENT_DATE": "2026-07-30T09:00:00+00:00",
        }
    ]
    merged, changed = merge_security_def_contracts(underlying, security_def)
    assert changed == 0
    assert merged[0]["eventMetaEVENT_DATE"] == "2026-07-31T09:00:00+00:00"


def test_merge_security_def_appends_new_ids():
    underlying = [{"SecurityID": "A", "publish_time": "2026-07-30T10:00:00+00:00"}]
    security_def = [{"SecurityID": "B", "publish_time": "2026-07-30T11:00:00+00:00"}]
    merged, changed = merge_security_def_contracts(underlying, security_def)
    assert changed == 1
    assert {c["SecurityID"] for c in merged} == {"A", "B"}


def test_fetch_contracts_refreshes_stale_security_def():
    from fetch.crypto_com import fetch_contracts

    primary = [
        {
            "SecurityID": "ML-001",
            "publish_time": "2026-07-29T12:00:00+00:00",
            "eventMetaEVENT_DATE": "2026-07-30T09:00:00+00:00",
            "source_type": "UnderlyingCatalogue",
        }
    ]
    sd = [
        {
            "SecurityID": "ML-001",
            "publish_time": "2026-07-30T08:00:00+00:00",
            "eventMetaEVENT_DATE": "2026-07-31T09:00:00+00:00",
            "source_type": "SecurityDef",
        }
    ]
    with (
        patch("fetch.crypto_com.ro_client", return_value=MagicMock()),
        patch(
            "fetch.crypto_com.fetch_security_def_contracts",
            return_value=(sd, 0, None, 1),
        ),
        patch(
            "fetch.crypto_com.build_catalogue_from_underlying",
            return_value=(primary, UnderlyingStats(game_lines=1), 1, None),
        ),
    ):
        contracts, _, _, _, _, sd_added = fetch_contracts(60)
    assert len(contracts) == 1
    assert sd_added == 1
    assert contracts[0]["eventMetaEVENT_DATE"] == "2026-07-31T09:00:00+00:00"
