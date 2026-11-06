"""Mapping invariants on a two-fighter reproduction of the 2026-09-29 flip.

The fixture is the real shape of Court McGee vs Eric Nolan on prod
snapshot 2026-09-30T15:00: crypto.com lists Nolan as HOME, Optic lists
McGee as HOME, and the buggy engine pinned each fighter's crypto id to
the opponent.
"""

import json

from regression.invariants import Catalogues, check, compare, load_records, main

SYM_MCGEE = "NX.F.OPT.UFC-00009-261003-M.O.1.1.20261229"
SYM_NOLAN = "NX.F.OPT.UFC-00009-261003-M.O.1.2.20261229"
FX = "20261003E0E8518E"


def _tick(tmp_path):
    tick = tmp_path / "2026-09-30" / "15_00"
    tick.mkdir(parents=True)
    crypto = [
        {"Symbol": SYM_MCGEE, "eventMetaPARTICIPANT": "Court McGee", "eventName": "Court McGee to win"},
        {"Symbol": SYM_NOLAN, "eventMetaPARTICIPANT": "Eric Nolan", "eventName": "Eric Nolan to win"},
    ]
    (tick / "crypto_com_markets.jsonl").write_text("".join(json.dumps(r) + "\n" for r in crypto))
    kalshi = [
        {"ticker": "KXUFC-MCG", "yes_sub_title": "Court McGee"},
        {"ticker": "KXUFC-NOL", "yes_sub_title": "Eric Nolan"},
    ]
    (tick / "kalshi_markets.jsonl").write_text("".join(json.dumps(r) + "\n" for r in kalshi))
    optic = {
        "id": FX,
        "odds": [
            {
                "market_id": "moneyline",
                "selection": "Court McGee",
                "source_ids": {"Kalshi": {"market_id": "KXUFC-MCG", "selection_id": "yes"}},
            },
            {
                "market_id": "moneyline",
                "selection": "Eric Nolan",
                "source_ids": {"Kalshi": {"market_id": "KXUFC-NOL", "selection_id": "yes"}},
            },
        ],
    }
    (tick / "optic_fixtures_odds.jsonl").write_text(json.dumps(optic) + "\n")
    return tick


def _rec(side, selection, crypto_sym=None, kalshi=None):
    return {
        "key": {
            "league": "ufc",
            "start_date": "2026-10-03T20:00:00Z",
            "home": "CMO8",
            "away": "ENR5",
            "market_type": "moneyline",
            "entity": None,
            "line": None,
            "side": side,
            "grouping_key": None,
        },
        "check": {"optic_selection": selection},
        "optic_odds": {"fixture_id": FX, "market_id": "moneyline", "selection": selection, "source_ids": {}},
        "crypto_com": ({"symbol": crypto_sym, "security_id": crypto_sym[-6:]} if crypto_sym else None),
        "kalshi": ({"market_ticker": kalshi, "side": "yes"} if kalshi else None),
        "prophet_x": None,
    }


GOOD = [_rec("CMO8", "Court McGee", SYM_MCGEE, "KXUFC-MCG"), _rec("ENR5", "Eric Nolan", SYM_NOLAN, "KXUFC-NOL")]
FLIPPED = [_rec("CMO8", "Court McGee", SYM_NOLAN, "KXUFC-MCG"), _rec("ENR5", "Eric Nolan", SYM_MCGEE, "KXUFC-NOL")]


def _fails(violations):
    return sorted((x.rule, x.contract) for x in violations if x.severity == "FAIL")


def test_correct_mapping_has_no_violations(tmp_path):
    assert _fails(check(GOOD, Catalogues.load(_tick(tmp_path)))) == []


def test_the_incident_fails_on_its_own_without_a_baseline(tmp_path):
    got = _fails(check(FLIPPED, Catalogues.load(_tick(tmp_path))))
    assert got == [("venue_label_swapped", SYM_MCGEE), ("venue_label_swapped", SYM_NOLAN)]


def test_optic_disagreement_on_kalshi(tmp_path):
    recs = [_rec("CMO8", "Court McGee", kalshi="KXUFC-NOL")]
    got = _fails(check(recs, Catalogues.load(_tick(tmp_path))))
    assert ("optic_disagrees", "KXUFC-NOL:yes") in got


def test_kalshi_no_side_is_a_bet_on_the_opponent(tmp_path):
    rec = _rec("ENR5", "Eric Nolan")
    rec["kalshi"] = {"market_ticker": "KXUFC-MCG", "side": "no"}
    got = _fails(check([rec, GOOD[0]], Catalogues.load(_tick(tmp_path))))
    assert ("venue_label_swapped", "KXUFC-MCG:no") not in got


def test_contract_reused_on_two_sides(tmp_path):
    recs = [_rec("CMO8", "Court McGee", SYM_MCGEE), _rec("ENR5", "Eric Nolan", SYM_MCGEE)]
    got = _fails(check(recs, Catalogues.load(_tick(tmp_path))))
    assert ("contract_reused", SYM_MCGEE) in got


def test_baseline_relative_split(tmp_path):
    cats = Catalogues.load(_tick(tmp_path))
    # candidate breaks it -> new; both broken -> existing; fixed -> fixed
    v = compare(check(FLIPPED, cats), check(GOOD, cats))
    assert len(v.new) == 2 and v.failed
    v = compare(check(FLIPPED, cats), check(FLIPPED, cats))
    assert not v.new and len(v.existing) == 2 and not v.failed
    v = compare(check(GOOD, cats), check(FLIPPED, cats))
    assert not v.failed and len(v.fixed) == 2
    assert compare(check(FLIPPED, cats), check(FLIPPED, cats), strict=True).failed


def test_records_without_optic_are_not_published(tmp_path):
    p = tmp_path / "out.json"
    rec = dict(FLIPPED[0], optic_odds=None)
    p.write_text(json.dumps(rec) + "\n" + json.dumps(GOOD[0]) + "\n")
    assert len(load_records(p)) == 1


def test_cli_exit_codes(tmp_path, capsys):
    tick = _tick(tmp_path)
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text("".join(json.dumps(r) + "\n" for r in GOOD))
    bad.write_text("".join(json.dumps(r) + "\n" for r in FLIPPED))
    assert main([str(good), str(tick)]) == 0
    assert main([str(bad), str(tick), "--baseline", str(good)]) == 1
    assert "venue says 'Eric Nolan'" in capsys.readouterr().out
    assert main([str(bad), str(tick), "--baseline", str(bad)]) == 0


def test_underdog_and_sx_contracts_reused_fail_without_a_label_check(tmp_path):
    ud = {"market_id": "UDXUFCGAMEWIN_X", "selection_id": "yes"}
    sx = {"event_id": "L1", "market_id": "0xabc", "selection_id": "0xabc|one"}
    recs = [
        dict(_rec("CMO8", "Court McGee"), underdog=ud, sxbet=sx),
        dict(_rec("ENR5", "Eric Nolan"), underdog=ud, sxbet=sx),
    ]
    got = check(recs, Catalogues.load(_tick(tmp_path)))
    assert _fails(got) == [("contract_reused", "0xabc|one"), ("contract_reused", "UDXUFCGAMEWIN_X:yes")]
    assert not [x for x in got if x.rule == "label_unverified"]
