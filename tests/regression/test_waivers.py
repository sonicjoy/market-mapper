"""Waiver contract tests: file validation (blanket rejection, typo
rejection, far-future expiry), matching, ceilings, expiry, staleness."""
import datetime
import json

import pytest

from regression.waivers import WaiverError, classify, load_waivers

TODAY = datetime.date(2026, 8, 12)

GOOD = '''
[[waiver]]
id = "mlb-poly-f5"
reason = "F5 poly enablement (MM-231, e5666a5)"
match = { direction = "added", league = "mlb", sportsbook = "polymarket", market_type_prefix = "f5_" }
max_rows = 300
expires = 2026-09-11
'''


def _load(tmp_path, text):
    p = tmp_path / "waivers.toml"
    p.write_text(text)
    return load_waivers(p, TODAY)


def _delta(direction="added", league="mlb", sb="polymarket",
           market_type="f5_total"):
    return {"direction": direction,
            "rec": {"k": [league, "2026-07-29", "PIT", "ARI",
                          market_type, None, 2.5, "over", None],
                    "sb": sb, "stamp": {"selection_id": "TOK"}},
            "raw": json.dumps({"k": [league]})}


def test_valid_file_loads(tmp_path):
    [w] = _load(tmp_path, GOOD)
    assert w["id"] == "mlb-poly-f5"
    assert w["expires"] == datetime.date(2026, 9, 11)


def test_empty_file_is_strict_gate(tmp_path):
    assert _load(tmp_path, "# no waivers\n") == []


def test_blanket_waiver_rejected(tmp_path):
    with pytest.raises(WaiverError, match="blanket"):
        _load(tmp_path, GOOD.replace(
            'match = { direction = "added", league = "mlb", '
            'sportsbook = "polymarket", market_type_prefix = "f5_" }',
            'match = { direction = "added" }'))


def test_typo_in_match_rejected(tmp_path):
    with pytest.raises(WaiverError, match="widen"):
        _load(tmp_path, GOOD.replace("market_type_prefix", "market_typo"))


def test_far_future_expiry_rejected(tmp_path):
    with pytest.raises(WaiverError, match="far-future"):
        _load(tmp_path, GOOD.replace("2026-09-11", "2027-08-12"))


def test_missing_required_fields_all_reported(tmp_path):
    with pytest.raises(WaiverError) as e:
        _load(tmp_path, '[[waiver]]\nid = "x"\n')
    for f in ("reason", "match", "max_rows", "expires"):
        assert f in str(e.value)


def _waiver(**over):
    w = {"id": "mlb-poly-f5", "reason": "MM-231",
         "match": {"direction": "added", "league": "mlb",
                   "sportsbook": "polymarket",
                   "market_type_prefix": "f5_"},
         "max_rows": 300, "expires": datetime.date(2026, 9, 11)}
    w.update(over)
    return w


def test_classify_waives_matching_deltas():
    deltas = [_delta(), _delta(market_type="f5_point_spread")]
    waived, unexplained, notes = classify(deltas, [_waiver()], TODAY)
    assert len(waived["mlb-poly-f5"]) == 2
    assert unexplained == []
    assert notes == {"stale": [], "breached": {}, "expired": {}}


def test_unmatched_deltas_unexplained():
    # same territory, wrong direction; and wrong sportsbook
    deltas = [_delta(direction="removed"), _delta(sb="kalshi")]
    waived, unexplained, _ = classify(deltas, [_waiver()], TODAY)
    assert waived == {} and len(unexplained) == 2


def test_breach_waives_nothing():
    deltas = [_delta() for _ in range(3)]
    waived, unexplained, notes = classify(
        deltas, [_waiver(max_rows=2)], TODAY)
    assert waived == {}
    assert len(unexplained) == 3
    assert notes["breached"] == {"mlb-poly-f5": 3}


def test_expired_waiver_stops_matching():
    deltas = [_delta()]
    waived, unexplained, notes = classify(
        deltas, [_waiver(expires=datetime.date(2026, 8, 11))], TODAY)
    assert waived == {} and len(unexplained) == 1
    assert notes["expired"] == {"mlb-poly-f5": 1}


def test_stale_waiver_reported():
    _, _, notes = classify([], [_waiver()], TODAY)
    assert notes["stale"] == ["mlb-poly-f5"]


def test_first_matching_waiver_takes_the_delta():
    w1 = _waiver(id="specific",
                 match={"direction": "added", "league": "mlb",
                        "sportsbook": "polymarket",
                        "market_type": "f5_total"})
    w2 = _waiver(id="broad")
    waived, _, notes = classify([_delta()], [w1, w2], TODAY)
    assert list(waived) == ["specific"]
    assert notes["stale"] == ["broad"]
