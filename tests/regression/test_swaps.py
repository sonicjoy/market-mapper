"""Side-swap detection and its waiver rule."""

import datetime
import io
import json

from regression.diff import run
from regression.swaps import find_swaps
from regression.waivers import classify, load_waivers

SYM1 = "NX.F.OPT.UFC-00009-261003-M.O.1.1.20261229"
SYM2 = "NX.F.OPT.UFC-00009-261003-M.O.1.2.20261229"


def _canon(side, sym, line=None, fixture="FX1"):
    return json.dumps(
        {
            "k": ["ufc", "2026-10-03T20:00:00Z", "CMO8", "ENR5", "moneyline", None, line, side, None],
            "sb": "crypto_com",
            "stamp": {"security_id": sym[-5:], "symbol": sym},
            "parent": {"fixture_id": fixture, "optic_market_id": "moneyline"},
        },
        sort_keys=True,
    )


def _deltas(removed, added):
    return [{"direction": "removed", "rec": json.loads(s), "raw": s} for s in removed] + [
        {"direction": "added", "rec": json.loads(s), "raw": s} for s in added
    ]


def test_exchanged_stamps_are_two_swaps():
    ds = _deltas([_canon("CMO8", SYM1), _canon("ENR5", SYM2)], [_canon("CMO8", SYM2), _canon("ENR5", SYM1)])
    swaps = find_swaps(ds)
    assert len(swaps) == 2
    assert all(d.get("swap") for d in ds)
    moved = {s["stamp"]["symbol"]: (s["from_side"], s["to_side"]) for s in swaps}
    assert moved[SYM1] == ("CMO8", "ENR5")


def test_spread_line_sign_moves_with_the_side():
    ds = _deltas([_canon("CMO8", SYM1, line=-1.5)], [_canon("ENR5", SYM1, line=1.5)])
    assert len(find_swaps(ds)) == 1


def test_same_side_restamp_and_other_fixture_are_not_swaps():
    ds = _deltas([_canon("CMO8", SYM1)], [_canon("CMO8", SYM2), _canon("ENR5", SYM1, fixture="FX2")])
    assert find_swaps(ds) == []
    assert not any(d.get("swap") for d in ds)


WAIVER = """
[[waiver]]
id = "ufc-crypto-churn"
reason = "test (MM-000)"
match = { direction = "added", league = "ufc", sportsbook = "crypto_com" }
max_rows = 10
expires = 2026-10-20
"""
SWAP_WAIVER = WAIVER.replace('sportsbook = "crypto_com" }', 'sportsbook = "crypto_com", side_swap = true }')


def _load(tmp_path, text):
    p = tmp_path / "w.toml"
    p.write_text(text)
    return load_waivers(p, datetime.date(2026, 10, 1))


def test_ordinary_waiver_never_excuses_a_swap(tmp_path):
    ds = _deltas([_canon("CMO8", SYM1)], [_canon("ENR5", SYM1)])
    find_swaps(ds)
    added = [d for d in ds if d["direction"] == "added"]
    _, unexplained, _ = classify(added, _load(tmp_path, WAIVER), datetime.date(2026, 10, 1))
    assert unexplained == added


def test_side_swap_waiver_excuses_only_swaps(tmp_path):
    ds = _deltas([_canon("CMO8", SYM1)], [_canon("ENR5", SYM1), _canon("CMO8", SYM2)])
    find_swaps(ds)
    added = [d for d in ds if d["direction"] == "added"]
    waived, unexplained, _ = classify(added, _load(tmp_path, SWAP_WAIVER), datetime.date(2026, 10, 1))
    assert [d["rec"]["k"][7] for d in waived["ufc-crypto-churn"]] == ["ENR5"]
    assert [d["rec"]["k"][7] for d in unexplained] == ["CMO8"]


def test_side_swap_false_is_rejected(tmp_path):
    import pytest

    from regression.waivers import WaiverError

    with pytest.raises(WaiverError, match="side_swap may only be true"):
        _load(tmp_path, WAIVER.replace('sportsbook = "crypto_com" }', 'sportsbook = "crypto_com", side_swap = false }'))


def test_gate_report_prints_swaps_first(tmp_path):
    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    a.write_text(_canon("CMO8", SYM1) + "\n" + _canon("ENR5", SYM2) + "\n")
    b.write_text(_canon("CMO8", SYM2) + "\n" + _canon("ENR5", SYM1) + "\n")
    w = tmp_path / "w.toml"
    w.write_text("")
    out, result = io.StringIO(), {}
    code = run(str(a), str(b), out=out, waivers_path=w, today=datetime.date(2026, 10, 1), result=result)
    text = out.getvalue()
    assert code == 1
    assert text.index("SIDE SWAPS: 2") < text.index("GATE FAIL")
    assert len(result["swaps"]) == 2 and len(result["unexplained"]) == 4
