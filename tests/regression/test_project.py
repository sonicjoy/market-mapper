"""Projector contract tests: explosion grain, exclusions,
normalization, source_ids passthrough, and loader-gate mirroring."""
import json

from regression.project import project_all


def _record(**over):
    """A minimal benchmark record; override any top-level field."""
    rec = {
        "key": {"sport": "basketball", "league": "wnba",
                "start_date": "2026-07-31T00:00:00Z",
                "home": "TOR", "away": "MIN",
                "market_type": "point_spread", "entity": None,
                "line": -18.5, "side": "MIN", "grouping_key": None},
        "check": {"kalshi_title": "human text, excluded"},
        "optic_odds": {"fixture_id": "FIX1", "market_id": "point_spread",
                       "selection": "Minnesota Lynx",
                       "selection_line": "", "points": -18.5},
        "kalshi": {"market_ticker": "KXWNBASPREAD-26JUL30MINTOR-MIN19",
                   "side": "yes"},
        "prophet_x": None,
        "crypto_com": None,
        "polymarket": None,
    }
    rec.update(over)
    return rec


def _lines(*records):
    return [json.dumps(r) for r in records]


def test_one_line_per_sportsbook_stamp():
    rec = _record(prophet_x={"event_id": "E1", "line_id": "L1"})
    out, stats = project_all(_lines(rec))
    assert stats == {"records": 1, "rowless": 0, "rows": 2}
    sbs = sorted(json.loads(line)["sb"] for line in out)
    assert sbs == ["kalshi", "prophet_x"]


def test_rowless_records_skipped_but_counted():
    out, stats = project_all(_lines(_record(kalshi=None)))
    assert out == []
    assert stats["rowless"] == 1


def test_no_optic_odds_no_rows():
    # loader: without an Optic join there is nothing to publish,
    # even when a constructed block is present
    out, stats = project_all(_lines(_record(optic_odds=None)))
    assert out == []
    assert stats["rowless"] == 1


def test_check_block_and_odd_values_excluded():
    a, _ = project_all(_lines(_record()))
    b, _ = project_all(_lines(_record(
        check={"kalshi_title": "DIFFERENT text"},
        optic_odds={"fixture_id": "FIX1", "market_id": "point_spread",
                    "selection": "renamed", "selection_line": "over",
                    "points": 0.0})))
    assert a == b  # only key, stamp, and parent pointer are compared


def test_parent_pointer_is_compared():
    a, _ = project_all(_lines(_record()))
    moved = dict(_record()["optic_odds"], fixture_id="FIX2")
    b, _ = project_all(_lines(_record(optic_odds=moved)))
    assert a != b  # re-attaching to another fixture is a real change


def test_line_float_drift_normalized():
    # Drift in BOTH key.line and optic points (they derive from the
    # same odd) is invisible: norm_line snaps the key, and the line
    # gate compares the drifted pair equal.  Key-only drift is NOT
    # invisible — the loader's exact-equality gate would drop the
    # published row (see test_line_gate below).
    a, _ = project_all(_lines(_record()))
    key = dict(_record()["key"], line=-18.500000000000004)
    odd = dict(_record()["optic_odds"], points=-18.500000000000004)
    b, _ = project_all(_lines(_record(key=key, optic_odds=odd)))
    assert a == b


def test_output_sorted_and_stable():
    r1 = _record()
    key2 = dict(_record()["key"], side="TOR", line=18.5)
    r2 = _record(key=key2, kalshi={"market_ticker": "T2", "side": "no"})
    out_ab, _ = project_all(_lines(r1, r2))
    out_ba, _ = project_all(_lines(r2, r1))
    assert out_ab == out_ba == sorted(out_ab)


def _with_src(**source_ids):
    odd = dict(_record()["optic_odds"], source_ids=source_ids)
    return _record(optic_odds=odd)


def test_passthrough_source_ids_emitted_verbatim():
    novig = {"event_id": "N1", "market_id": "N2", "selection_id": "N3"}
    out, _ = project_all(_lines(_with_src(**{
        "Novig": novig, "Polymarket (USA)": {"market_id": "PU1"}})))
    rows = {json.loads(s)["sb"]: json.loads(s)["stamp"] for s in out}
    assert rows["novig"] == novig
    assert rows["polymarket_usa"] == {"market_id": "PU1"}
    assert "kalshi" in rows  # constructed stamps unaffected


def test_polymarket_dedup_passthrough_wins():
    # Same token, two provenances: matcher-constructed vs optic
    # passthrough.  Both must project to ONE identical line, so a
    # change that merely flips the path is not a false diff.
    constructed = _record(kalshi=None,
                          polymarket={"clob_token_id": "TOK"})
    src = _with_src(**{"Polymarket": {"selection_id": "TOK"}})
    passthrough = dict(src, kalshi=None,
                       polymarket={"clob_token_id": "TOK"})
    a, _ = project_all(_lines(constructed))
    b, _ = project_all(_lines(passthrough))
    assert a == b
    [line] = a
    assert json.loads(line)["stamp"] == {"selection_id": "TOK"}


def test_line_gate_drops_constructed_keeps_passthrough():
    # key.line genuinely disagreeing with optic points: the loader
    # publishes no constructed stamps (missing > wrong) but keeps
    # the Optic passthrough — mirror both halves.
    rec = _with_src(**{"SX Bet": {"selection_id": "SX1"}})
    rec["optic_odds"] = dict(rec["optic_odds"], points=-19.0)
    out, _ = project_all(_lines(rec))
    assert [json.loads(s)["sb"] for s in out] == ["sx_bet"]


def test_crypto_gate_on_pm_npo_disagreement():
    cc = {"security_id": "S1", "symbol": "SYM",
          "market_id": "PM.NPO.AAA"}
    agree = _with_src(**{"crypto.com": {"market_id": "PM.NPO.AAA"}})
    agree = dict(agree, kalshi=None, crypto_com=cc)
    disagree = _with_src(**{"crypto.com": {"market_id": "PM.NPO.BBB"}})
    disagree = dict(disagree, kalshi=None, crypto_com=cc)
    out_a, _ = project_all(_lines(agree))
    out_d, _ = project_all(_lines(disagree))
    assert [json.loads(s)["sb"] for s in out_a] == ["crypto_com"]
    assert out_d == []  # crypto.com is not a passthrough sportsbook


UD = {"market_id": "UDXMLSTEAMTOTAL_ATLNYC26OCT28_ATL0.5", "selection_id": "yes"}
SX = {"event_id": "L1", "market_id": "0xabc", "selection_id": "0xabc|one", "type": 3}


def test_underdog_stamp_is_projected():
    out, _ = project_all(_lines(_record(kalshi=None, underdog=UD)))
    assert [json.loads(s)["stamp"] for s in out] == [UD]


def test_an_underdog_satellite_emits_its_underdog_stamp_alone():
    rec = _with_src(Novig={"selection_id": "N3"})
    rec.update(underdog=UD, underdog_satellite=True)
    out, _ = project_all(_lines(rec))
    assert [json.loads(s)["sb"] for s in out] == ["underdog"]


def test_constructed_sx_matches_the_passthrough_it_stands_in_for():
    ids = {f: SX[f] for f in ("event_id", "market_id", "selection_id")}
    constructed, _ = project_all(_lines(_record(kalshi=None, sxbet=SX)))
    passthrough, _ = project_all(_lines(dict(_with_src(**{"SX Bet": ids}), kalshi=None, sxbet=SX)))
    assert constructed == passthrough  # one MERGE key: the loader emits only one of them
    assert json.loads(constructed[0])["stamp"] == ids


STX = {"market_id": "0a0b4f52", "selection_id": "yes", "event_id": "E1", "tie_pays_half": True}


def test_stx_stamp_is_projected_with_its_tie_flag():
    out, _ = project_all(_lines(_record(kalshi=None, stx=STX)))
    assert [json.loads(s)["stamp"] for s in out] == [
        {"market_id": "0a0b4f52", "selection_id": "yes", "tie_pays_half": True}
    ]


def test_an_stx_satellite_emits_its_stx_stamp_alone():
    rec = _with_src(Novig={"selection_id": "N3"})
    rec.update(stx=STX, stx_satellite=True)
    out, _ = project_all(_lines(rec))
    assert [json.loads(s)["sb"] for s in out] == ["stx"]


def test_a_flipped_tie_flag_changes_the_projection():
    a, _ = project_all(_lines(_record(kalshi=None, stx=STX)))
    b, _ = project_all(_lines(_record(kalshi=None, stx=dict(STX, tie_pays_half=False))))
    assert a != b  # the gate shows a flag change as a row delta
