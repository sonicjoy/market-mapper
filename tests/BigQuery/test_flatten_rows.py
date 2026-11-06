"""Tests for flatten_rows — pure transform, no BQ connection.

flatten_rows turns one nested mapping record (the canonical_row_to_json
shape) into one flat staging row per exchange (sportsbook).
"""

from BigQuery.load_mappings import flatten_rows

NOW = "2026-06-09T15:00:00+00:00"

# A World Cup 3-way Draw row that merged across Optic + Kalshi + crypto
# (the USA v Paraguay shape from the WC crypto integration fixture).
_REC = {
    "key": {
        "sport": "soccer", "league": "world_cup",
        "start_date": "2026-06-13T01:00:00Z",
        "home": "USA", "away": "PAR", "market_type": "moneyline_3way",
        "entity": None, "line": None, "side": "_TIE",
        "grouping_key": None,
    },
    "optic_odds": {
        "fixture_id": "202606137F8800D2",
        "game_id": "68310-10747-2026-06-12",
        "market_id": "moneyline", "selection": "Draw",
        "selection_line": "", "points": 0.0, "grouping_key": "default",
        "source_ids": {},
    },
    "kalshi": {"market_ticker": "KXWCGAME-26JUN12USAPAR-TIE",
               "side": "yes"},
    "prophet_x": None,
    "crypto_com": {
        "security_id": "202512221502380000362111D",
        "symbol": "NX.F.OPT.FIFA-00001-260612-M.O.1.1",
        "market_id": "20251222140021644",
        "outcome_id": "20251222140025145",
        "selection_name": "Draw to win",
    },
}


def _mapping_rec(*, kalshi=None, prophet_x=None, optic_source_ids=None):
    return {
        "key": {
            "league": "nba",
            "start_date": "2026-03-08T00:00:00Z",
            "home": "BOS",
            "away": "CLE",
            "market_type": "moneyline",
            "entity": None,
            "line": None,
            "side": "BOS",
            "grouping_key": None,
        },
        "optic_odds": {
            "fixture_id": "FIX1",
            "game_id": "g1",
            "market_id": "moneyline",
            "selection": "Boston Celtics",
            "selection_line": "",
            "points": 0.0,
            "grouping_key": "default",
            "source_ids": optic_source_ids,
        },
        "kalshi": kalshi,
        "prophet_x": prophet_x,
    }


def test_flatten_rows_emits_prediction_markets_from_optic_source_ids():
    rec = _mapping_rec(
        optic_source_ids={
            "Polymarket": {"selection_id": "poly-token"},
            "Novig": {"selection_id": "novig-token"},
            "Polymarket (USA)": {"selection_id": "poly-usa-token"},
        },
    )

    rows = list(flatten_rows(rec, "2026-06-10T00:00:00+00:00"))
    by_sb = {row["sportsbook"]: row for row in rows}

    assert set(by_sb) == {"Polymarket", "Novig", "Polymarket (USA)"}
    assert by_sb["Polymarket"]["source_ids"] == {"selection_id": "poly-token"}
    assert by_sb["Novig"]["game_id"] == "g1"


def test_flatten_rows_emits_kalshi_and_prediction_markets_together():
    rec = _mapping_rec(
        kalshi={"market_ticker": "KXNBAGAME-TEST", "side": "yes"},
        optic_source_ids={
            "Kalshi": {"market_id": "KXNBAGAME-TEST", "selection_id": "yes"},
            "Polymarket": {"selection_id": "poly-token"},
        },
    )

    rows = list(flatten_rows(rec, "2026-06-10T00:00:00+00:00"))
    sportsbooks = {row["sportsbook"] for row in rows}

    assert sportsbooks == {"Kalshi", "Polymarket"}
    kalshi_rows = [r for r in rows if r["sportsbook"] == "Kalshi"]
    assert len(kalshi_rows) == 1
    assert kalshi_rows[0]["source_ids"]["market_id"] == "KXNBAGAME-TEST"


def test_prediction_market_only_rows_are_load_eligible():
    """Rows with only Polymarket/Novig IDs must reach markets_us.market_mapping.

    load() skips a record only when flatten_rows yields nothing.  Prediction-
    market-only records (no Kalshi/PX match) must not be treated as optic-only
    discards.
    """
    rec = _mapping_rec(
        optic_source_ids={"Polymarket": {"selection_id": "poly-only"}},
    )
    assert list(flatten_rows(rec, "2026-06-10T00:00:00+00:00"))


def test_crypto_row_uses_crypto_vocab_source_ids():
    """The crypto.com row carries its own FIX vocabulary (SecurityID +
    Symbol) in source_ids — not the generic market_id/selection_id."""
    rows = list(flatten_rows(_REC, NOW))
    crypto = [r for r in rows if r["sportsbook"] == "crypto.com"]
    assert len(crypto) == 1
    (c,) = crypto
    # FIX-only predict market_id is not Optic PM.NPO — omit from emit.
    assert c["source_ids"] == {
        "security_id": "202512221502380000362111D",
        "symbol": "NX.F.OPT.FIFA-00001-260612-M.O.1.1",
    }
    assert "source_symbol" not in c
    # Rides the Optic-derived base + the canonical key.
    assert c["side"] == "_TIE"
    assert c["market_type"] == "moneyline_3way"
    assert c["game_id"] == "68310-10747-2026-06-12"
    assert c["market_id"] == "moneyline"
    assert c["last_updated"] == NOW


def test_non_crypto_rows_have_no_source_symbol_field():
    """Symbol identity is source_ids.symbol only; no denormalized column."""
    rows = list(flatten_rows(_REC, NOW))
    kalshi = [r for r in rows if r["sportsbook"] == "Kalshi"]
    assert len(kalshi) == 1
    assert "source_symbol" not in kalshi[0]
    assert "symbol" not in (kalshi[0].get("source_ids") or {})


def test_crypto_row_includes_optic_market_id_when_decoded():
    """Optic-decoded stamps dual-write PM.NPO market_id into source_ids."""
    rec = {
        **_REC,
        "crypto_com": {
            **_REC["crypto_com"],
            "market_id": (
                "FIFA-00001-260612-M-MLDraw-O11_260830-2300_1_PM.NPO"
            ),
        },
    }
    rows = list(flatten_rows(rec, NOW))
    crypto = [r for r in rows if r["sportsbook"] == "crypto.com"]
    assert crypto[0]["source_ids"]["market_id"].endswith("PM.NPO")
    assert crypto[0]["source_ids"]["symbol"].startswith("NX.F.OPT.")
    # Never double-emit via OPTIC_MAPPED passthrough.
    assert sum(1 for r in rows if r["sportsbook"] == "crypto.com") == 1


def test_merged_record_yields_one_row_per_present_exchange():
    """Optic+Kalshi+crypto present, PX null → Kalshi and crypto rows
    (the base is Optic-derived; there is no standalone Optic row)."""
    rows = list(flatten_rows(_REC, NOW))
    assert {r["sportsbook"] for r in rows} == {"Kalshi", "crypto.com"}


def test_flatten_rows_emits_runshop():
    rec = {
        **_REC,
        "runshop": {"tx_odds_fixture_id": 905827989, "market_id": 3},
    }
    rows = list(flatten_rows(rec, NOW))
    runshop_rows = [r for r in rows if r["sportsbook"] == "Runshop"]
    assert len(runshop_rows) == 1
    assert runshop_rows[0]["source_ids"] == {
        "fixture_id": "905827989",
        "market_id": "3",
    }


def test_no_runshop_without_optic():
    rec = {
        **_REC,
        "optic_odds": None,
        "runshop": {"tx_odds_fixture_id": 905827989, "market_id": 3},
    }
    rows = list(flatten_rows(rec, NOW))
    assert all(r["sportsbook"] != "Runshop" for r in rows)


def test_flatten_rows_emits_huddle():
    rec = {
        **_REC,
        "huddle": {
            "selection_id": "sel-1",
            "event_id": "ev-1",
            "market_id": "m-1",
        },
    }
    rows = list(flatten_rows(rec, NOW))
    huddle_rows = [r for r in rows if r["sportsbook"] == "Huddle"]
    assert len(huddle_rows) == 1
    assert huddle_rows[0]["source_ids"] == {
        "selection_id": "sel-1",
        "event_id": "ev-1",
        "market_id": "m-1",
    }


def test_no_crypto_block_yields_no_crypto_row():
    rec = {**_REC, "crypto_com": None}
    rows = list(flatten_rows(rec, NOW))
    assert all(r["sportsbook"] != "crypto.com" for r in rows)


def _polymarket_rec(optic_source_ids):
    return {
        "key": {
            "league": "mlb", "start_date": "2026-07-21T23:00:00Z",
            "home": "AZ", "away": "STL", "market_type": "game_total",
            "line": 8.5, "side": "over", "grouping_key": None,
        },
        "optic_odds": {
            "game_id": "g1", "fixture_id": "FX1", "market_id": "total_runs",
            "selection": "", "selection_line": "over", "points": 8.5,
            "grouping_key": "default", "source_ids": optic_source_ids,
        },
        "polymarket": {
            "clob_token_id": "cO", "condition_id": "0xabc",
            "position_id": "pO", "slug": "mlb-az-stl-2026-07-21",
            "question": "AZ vs. STL: O/U 8.5",
        },
    }


def test_flatten_rows_emits_constructed_polymarket_when_optic_unmapped():
    """optic_odds.source_ids has no "Polymarket" entry (optic-unmapped
    token) -> the matcher's constructed clob_token_id is the emitted row."""
    rec = _polymarket_rec(optic_source_ids={})
    rows = list(flatten_rows(rec, "2026-07-21T23:00:00Z"))
    poly = [r for r in rows if r["sportsbook"] == "Polymarket"]
    assert len(poly) == 1
    assert poly[0]["source_ids"] == {"selection_id": "cO"}
    assert poly[0]["fixture_id"] == "FX1" and poly[0]["market_id"] == "total_runs"


def test_flatten_rows_no_double_emit_when_optic_already_has_polymarket():
    """optic_odds.source_ids already carries a "Polymarket" entry -> the
    existing passthrough row wins; the constructed row must NOT also be
    emitted (same MERGE key -> would be a double-emit)."""
    rec = _polymarket_rec(
        optic_source_ids={"Polymarket": {"selection_id": "existing-optic-token"}},
    )
    rows = list(flatten_rows(rec, "2026-07-21T23:00:00Z"))
    poly = [r for r in rows if r["sportsbook"] == "Polymarket"]
    assert len(poly) == 1
    assert poly[0]["source_ids"] == {"selection_id": "existing-optic-token"}


def test_flatten_crypto_satellite_emits_crypto_com_only():
    """Inherited optic_id must not re-emit the parent's Polymarket token."""
    optic = {
        "game_id": "15260-54558-2026-08-20-15",
        "fixture_id": "20260820B3052EC3",
        "market_id": "player_home_runs",
        "selection": "Austin Wells",
        "selection_line": "over",
        "points": 0.5,
        "grouping_key": "austin_wells:0.5",
        "source_ids": {
            "Polymarket": {"selection_id": "poly-hr-token"},
            "Novig": {"selection_id": "novig-hr-token"},
        },
    }
    key = {
        "league": "mlb",
        "start_date": "2026-08-20T22:35:00Z",
        "home": "BAL",
        "away": "NYY",
        "market_type": "player_home_runs",
        "entity": "austin_wells",
        "line": 0.5,
        "side": "over",
        "grouping_key": None,
    }
    parent = {
        "key": key,
        "optic_odds": optic,
        "crypto_com": {
            "security_id": "SID-HIT",
            "symbol": "NX.F.OPT.MLB-00007-260820-M.O.1.88.20261130",
            "market_id": "m-hit",
            "outcome_id": "o-hit",
            "selection_name": "To Hit A Home Run",
        },
        "kalshi": {"market_ticker": "KXMLBHR-TEST-1", "side": "yes"},
    }
    satellite = {
        "key": key,
        "optic_odds": optic,
        "crypto_satellite": True,
        "crypto_com": {
            "security_id": "SID-MS",
            "symbol": "NX.F.OPT.MLB-00007-260820-M.O.1.325.20261130",
            "market_id": "m-ms",
            "outcome_id": "o-ms",
            "selection_name": "Total Home Runs Milestones",
        },
        "kalshi": {"market_ticker": "KXMLBHR-TEST-1", "side": "yes"},
    }
    parent_rows = list(flatten_rows(parent, NOW))
    sat_rows = list(flatten_rows(satellite, NOW))
    all_rows = parent_rows + sat_rows
    by_sb: dict[str, list] = {}
    for r in all_rows:
        by_sb.setdefault(r["sportsbook"], []).append(r)
    assert len(by_sb["Polymarket"]) == 1
    assert len(by_sb["Novig"]) == 1
    assert len(by_sb["Kalshi"]) == 1
    assert len(by_sb["crypto.com"]) == 2
    assert {r["source_ids"]["symbol"] for r in by_sb["crypto.com"]} == {
        "NX.F.OPT.MLB-00007-260820-M.O.1.88.20261130",
        "NX.F.OPT.MLB-00007-260820-M.O.1.325.20261130",
    }
    assert {r["sportsbook"] for r in sat_rows} == {"crypto.com"}


def test_flatten_kalshi_complement_emits_kalshi_only():
    """Opponent-No satellite must not re-emit PX/Poly on the parent MERGE key."""
    rec = {
        "key": {
            "league": "nfl",
            "start_date": "2026-09-14T20:00:00Z",
            "home": "KC",
            "away": "DEN",
            "market_type": "moneyline",
            "entity": None,
            "line": None,
            "side": "KC",
            "grouping_key": None,
        },
        "optic_odds": {
            "fixture_id": "FIX-NFL",
            "game_id": "g-nfl",
            "market_id": "moneyline",
            "selection": "Kansas City Chiefs",
            "selection_line": "",
            "points": 0.0,
            "grouping_key": "default",
            "source_ids": {
                "Polymarket": {"selection_id": "poly-chiefs"},
                "Novig": {"selection_id": "novig-chiefs"},
            },
        },
        "kalshi_complement": True,
        "kalshi": {
            "market_ticker": "KXNFLGAME-26SEP14DENKC-DEN",
            "side": "no",
        },
    }
    rows = list(flatten_rows(rec, NOW))
    assert len(rows) == 1
    assert rows[0]["sportsbook"] == "Kalshi"
    assert rows[0]["source_ids"] == {
        "market_id": "KXNFLGAME-26SEP14DENKC-DEN",
        "selection_id": "no",
    }



def test_flatten_kalshi_double_chance_complement():
    """Soccer GAME No satellite: Kalshi row on the Optic double chance odd."""
    rec = {
        "key": {
            "league": "uefa_nations_league",
            "start_date": "2026-09-26T18:45:00Z",
            "home": "ENG",
            "away": "ESP",
            "market_type": "double_chance",
            "entity": None,
            "line": None,
            "side": "ESP/_TIE",
            "grouping_key": None,
        },
        "optic_odds": {
            "fixture_id": "FIX-NL",
            "game_id": "11439-15802-2026-09-26",
            "market_id": "double_chance",
            "selection": "Spain Or Draw",
            "selection_line": "",
            "points": 0.0,
            "grouping_key": "default",
            "source_ids": {"Polymarket (USA)": {"market_id": "pusa-dc"}},
        },
        "kalshi_complement": True,
        "kalshi": {
            "market_ticker": "KXUEFANLGAME-26SEP26ENGESP-ENG",
            "side": "no",
        },
    }
    rows = list(flatten_rows(rec, NOW))
    assert len(rows) == 1
    assert rows[0]["sportsbook"] == "Kalshi"
    assert rows[0]["market_id"] == "double_chance"
    assert rows[0]["selection"] == "Spain Or Draw"
    assert rows[0]["source_ids"] == {
        "market_id": "KXUEFANLGAME-26SEP26ENGESP-ENG",
        "selection_id": "no",
    }

def test_flatten_polymarket_usa_double_chance_carries_its_no_side():
    """Soccer outcome No: the symbol plus selection_id "no" on the DC odd."""
    rec = {
        "key": {
            "league": "uefa_nations_league", "start_date": "2026-09-26T18:45:00Z",
            "home": "ENG", "away": "ESP", "market_type": "double_chance",
            "entity": None, "line": None, "side": "ENG/_TIE", "grouping_key": None,
        },
        "optic_odds": {
            "fixture_id": "FIX-NL", "game_id": "11439-15802-2026-09-26",
            "market_id": "double_chance", "selection": "England Or Draw",
            "selection_line": "", "points": 0.0, "grouping_key": "default",
            "source_ids": {},
        },
        "polymarket_usa": {
            "market_id": "atc-unl-eng-esp-2026-09-26-esp", "selection_id": "no",
        },
    }
    rows = list(flatten_rows(rec, NOW))
    usa = [r for r in rows if r["sportsbook"] == "Polymarket (USA)"]
    assert len(usa) == 1
    assert usa[0]["source_ids"] == {
        "market_id": "atc-unl-eng-esp-2026-09-26-esp", "selection_id": "no",
    }


def test_flatten_polymarket_usa_keeps_a_bare_market_id_without_a_side():
    rec = _mapping_rec(optic_source_ids={})
    rec["polymarket_usa"] = {"market_id": "aec-nba-bos-nyk-2026-10-21"}
    usa = [r for r in flatten_rows(rec, NOW) if r["sportsbook"] == "Polymarket (USA)"]
    assert usa[0]["source_ids"] == {"market_id": "aec-nba-bos-nyk-2026-10-21"}


def test_flatten_polymarket_usa_passthrough_gets_the_mappers_side():
    """Optic's own US stamp plus the side our typed bind derived for it."""
    rec = _mapping_rec(optic_source_ids={"Polymarket (USA)": {"market_id": "aec-nba-bos-nyk"}})
    rec["polymarket_usa"] = {"market_id": None, "selection_id": "yes"}
    usa = [r for r in flatten_rows(rec, NOW) if r["sportsbook"] == "Polymarket (USA)"]
    assert [u["source_ids"] for u in usa] == [{"market_id": "aec-nba-bos-nyk", "selection_id": "yes"}]


def test_flatten_polymarket_usa_passthrough_never_borrows_another_symbols_side():
    rec = _mapping_rec(optic_source_ids={"Polymarket (USA)": {"market_id": "aec-nba-bos-nyk"}})
    rec["polymarket_usa"] = {"market_id": "some-other-symbol", "selection_id": "no"}
    usa = [r for r in flatten_rows(rec, NOW) if r["sportsbook"] == "Polymarket (USA)"]
    assert [u["source_ids"] for u in usa] == [{"market_id": "aec-nba-bos-nyk"}]


def test_flatten_polymarket_usa_satellite_emits_the_us_symbol_only():
    """No team scores in 1H, priced off the under 0.5 odd: none of its books."""
    rec = {
        "key": {
            "league": "mls", "start_date": "2026-09-30T23:30:00Z",
            "home": "NYR", "away": "STL", "market_type": "1h_first_team_to_score",
            "entity": None, "line": None, "side": "_TIE", "grouping_key": None,
        },
        "optic_odds": {
            "fixture_id": "FIX-MLS", "game_id": "25622-28736-2026-09-30",
            "market_id": "1st_half_total_goals", "selection": "Under",
            "selection_line": "under", "points": 0.5, "grouping_key": "default",
            "source_ids": {
                "Polymarket (USA)": {"market_id": "tsc-mls-nyr-stl-2026-09-26-fh-0pt5"},
                "Novig": {"selection_id": "novig-under"},
            },
        },
        "polymarket_usa_satellite": True,
        "polymarket_usa": {
            "market_id": "astatc-mls-nyr-stl-2026-09-26-fh-ftts-none", "selection_id": "yes",
        },
    }
    rows = list(flatten_rows(rec, NOW))
    assert [(r["sportsbook"], r["source_ids"]) for r in rows] == [(
        "Polymarket (USA)",
        {"market_id": "astatc-mls-nyr-stl-2026-09-26-fh-ftts-none", "selection_id": "yes"},
    )]
    assert rows[0]["market_id"] == "1st_half_total_goals"
    assert rows[0]["market_type"] == "1h_first_team_to_score"


def _crypto_only_rec(cc_extra: dict | None = None) -> dict:
    """A crypto-only spread record (no Optic odd)."""
    cc = {
        "security_id": "202606071324552601809191D",
        "symbol": "NX.F.OPT.FIFA-00004-260622-M.O.1.10.20260830",
        "market_id": "202606071724521780853092143439814",
        "outcome_id": "202606071724521780853092244703310",
        "selection_name": "Iraq 6.5 to win",
    }
    cc.update(cc_extra or {})
    return {
        "key": {
            "sport": "soccer", "league": "world_cup",
            "start_date": "2026-06-22T21:00:00Z",
            "home": "FRA", "away": "IRQ", "market_type": "point_spread",
            "entity": None, "line": 6.5, "side": "IRQ",
            "grouping_key": None,
        },
        "optic_odds": None,
        "kalshi": None,
        "prophet_x": None,
        "crypto_com": cc,
    }


def test_crypto_without_optic_odds_emits_nothing():
    """No Optic market_id → no market_mapping row (including crypto.com).

    Novel/ladder crypto still maps in the pipeline JSONL; load waits until
    an Optic odd exists so every row carries a real Optic market_id.
    """
    assert list(flatten_rows(_crypto_only_rec(), NOW)) == []
    stamped = _crypto_only_rec({
        "fixture_id": "202606227F8800D2",
        "game_id": "68310-10747-2026-06-22",
    })
    stamped["kalshi"] = {
        "market_ticker": "KXTESTGAME-26AUG03HOMEAWAY-HOME",
        "side": "yes",
    }
    assert list(flatten_rows(stamped, NOW)) == []


def test_flatten_skips_crypto_when_pm_npo_market_id_disagrees():
    rec = {
        **_REC,
        "crypto_com": {
            **_REC["crypto_com"],
            "market_id": "UFC-X-M-ML-O11_261130-2300_1_PM.NPO",
        },
        "optic_odds": {
            **_REC["optic_odds"],
            "source_ids": {
                "crypto.com": {
                    "market_id": "UFC-Y-M-ML-O11_261130-2300_1_PM.NPO",
                },
            },
        },
    }
    rows = list(flatten_rows(rec, NOW))
    assert "crypto.com" not in {r["sportsbook"] for r in rows}
    assert "Kalshi" in {r["sportsbook"] for r in rows}


def test_flatten_line_mismatch_keeps_optic_passthrough():
    """Line disagree skips constructed stamps but not Optic source_ids books."""
    rec = _mapping_rec(
        kalshi={"market_ticker": "KXNBAGAME-TEST", "side": "yes"},
        optic_source_ids={
            "Polymarket": {"selection_id": "poly-token"},
            "Novig": {"selection_id": "novig-token"},
        },
    )
    rec["key"]["line"] = 5.5
    rec["key"]["market_type"] = "game_total"
    rec["key"]["side"] = "over"
    rec["optic_odds"]["points"] = 6.5
    rec["optic_odds"]["market_id"] = "total_points"
    rows = list(flatten_rows(rec, NOW))
    assert {r["sportsbook"] for r in rows} == {"Polymarket", "Novig"}


def test_flatten_keeps_kalshi_when_optic_source_ids_stale_disagree():
    """Mapper may keep our ticker while Optic source_ids cite a stale id."""
    rec = _mapping_rec(
        kalshi={"market_ticker": "KX-OUR", "side": "yes"},
        optic_source_ids={
            "Kalshi": {"market_id": "KX-STALE", "selection_id": "yes"},
        },
    )
    rows = list(flatten_rows(rec, NOW))
    assert {r["sportsbook"] for r in rows} == {"Kalshi"}
    assert rows[0]["source_ids"]["market_id"] == "KX-OUR"


# === Novig ===

_NOVIG_STAMP = {
    "event_id": "evt-1",
    "market_id": "mkt-1",
    "outcome_id": "out-1",
    "market_type": "MONEY",
    "description": "BOS",
}


def test_flatten_emits_constructed_novig_row():
    """A Novig outcome our matcher mapped that Optic never carried."""
    rec = _mapping_rec(optic_source_ids={})
    rec["novig"] = _NOVIG_STAMP

    rows = list(flatten_rows(rec, NOW))
    by_sb = {r["sportsbook"]: r for r in rows}

    assert set(by_sb) == {"Novig"}
    # Byte-identical in shape to Optic's own Novig source_ids, so downstream
    # joins cannot tell the constructed and passthrough paths apart.
    assert by_sb["Novig"]["source_ids"] == {
        "event_id": "evt-1", "market_id": "mkt-1", "selection_id": "out-1"}


def test_flatten_never_double_emits_novig():
    """Optic already carries this outcome — passthrough wins, no duplicate.

    Both paths would produce the same MERGE key, so emitting both trips the
    pre-merge duplicate-key assertion in load().
    """
    rec = _mapping_rec(
        optic_source_ids={"Novig": {"event_id": "evt-1",
                                    "market_id": "mkt-1",
                                    "selection_id": "out-1"}},
    )
    rec["novig"] = _NOVIG_STAMP

    rows = list(flatten_rows(rec, NOW))
    novig_rows = [r for r in rows if r["sportsbook"] == "Novig"]

    assert len(novig_rows) == 1
    assert novig_rows[0]["source_ids"]["selection_id"] == "out-1"


def test_flatten_line_mismatch_skips_constructed_novig():
    """key.line disagreeing with optic points drops constructed stamps."""
    rec = _mapping_rec(optic_source_ids={})
    rec["novig"] = _NOVIG_STAMP
    rec["key"]["line"] = 5.5
    rec["key"]["market_type"] = "game_total"
    rec["key"]["side"] = "over"
    rec["optic_odds"]["points"] = 6.5
    rec["optic_odds"]["market_id"] = "total_points"

    rows = list(flatten_rows(rec, NOW))
    assert "Novig" not in {r["sportsbook"] for r in rows}


def test_flatten_rows_tip_only_league_slug_is_soccer():
    """Tip-only slugs have no League enum; load must not raise."""
    rec = {
        **_REC,
        "key": {**_REC["key"], "league": "super_lig"},
    }
    rows = list(flatten_rows(rec, NOW))
    assert rows
    assert {r["league"] for r in rows} == {"super_lig"}
    assert {r["sport"] for r in rows} == {"soccer"}


def test_flatten_rows_includes_provenance_fields():
    rec = {**_REC, "provenance": {
        "mapping_run_id": "run-abc",
        "mapper_git_commit": "deadbeef",
        "mapping_logic_version": "pipeline_v1",
        "mapped_at": "2026-08-19T10:35:00+00:00",
        "fixture_match_method": "optic_schedule",
        "market_match_method": "kalshi_ticker",
    }}
    rows = list(flatten_rows(rec, NOW))
    assert rows
    for row in rows:
        assert row["mapping_run_id"] == "run-abc"
        assert row["fixture_match_method"] == "optic_schedule"
        assert row["market_match_method"] == "kalshi_ticker"


def test_flatten_rows_passes_betfair_exchange_ids_through_verbatim():
    """Betfair's event / market / selection ids reach market_mapping as Optic
    publishes them: the orderbook platform subscribes on market_id and picks
    the runner by selection_id."""
    src = {"event_id": "34851234", "market_id": "1.245678901",
           "selection_id": "237486"}
    rec = _mapping_rec(optic_source_ids={"Betfair Exchange": src})

    rows = list(flatten_rows(rec, NOW))

    assert [r["sportsbook"] for r in rows] == ["Betfair Exchange"]
    assert rows[0]["source_ids"] == src
    assert rows[0]["fixture_id"] == "FIX1"


def test_note_crypto_dropped_counts_only_crypto_records_without_optic():
    import collections

    from BigQuery.load_mappings import note_crypto_dropped
    c = collections.Counter()
    note_crypto_dropped({"key": {"league": "nba"}, "crypto_com": {"symbol": "S"}}, c)
    note_crypto_dropped({"key": {"league": "nba"}}, c)
    note_crypto_dropped({"crypto_com": {"symbol": "S"}}, c)
    assert dict(c) == {"nba": 1, "?": 1}
