"""Differ contract tests: exit semantics and delta bucketing."""
import io
import json

from regression.diff import run


def _canon(league, sb, market_type, ticker):
    return json.dumps(
        {"k": [league, "2026-07-31", "TOR", "MIN", market_type,
               None, -18.5, "MIN", None],
         "sb": sb, "stamp": {"market_ticker": ticker, "side": "yes"},
         "parent": {"fixture_id": "FIX1", "optic_market_id": market_type}},
        sort_keys=True)


def _write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def test_identical_exits_zero(tmp_path):
    lines = [_canon("wnba", "kalshi", "point_spread", "T1")]
    a = _write(tmp_path, "a.jsonl", lines)
    b = _write(tmp_path, "b.jsonl", lines)
    out = io.StringIO()
    assert run(a, b, out=out) == 0
    assert "IDENTICAL" in out.getvalue()


def test_delta_exits_nonzero_and_buckets(tmp_path):
    base = [_canon("wnba", "kalshi", "point_spread", "T1")]
    added = base + [_canon("mlb", "polymarket", "f5_total", "T2"),
                    _canon("mlb", "polymarket", "f5_total", "T3")]
    a = _write(tmp_path, "a.jsonl", base)
    b = _write(tmp_path, "b.jsonl", added)
    out = io.StringIO()
    assert run(a, b, out=out) == 1
    text = out.getvalue()
    assert "only in A (dropped by B): 0 rows" in text
    assert "only in B (added by B): 2 rows" in text
    assert "mlb" in text and "polymarket" in text and "f5_total" in text


GATE_WAIVER = '''
[[waiver]]
id = "wnba-kalshi-spread"
reason = "test waiver (MM-000)"
match = { direction = "added", league = "mlb", sportsbook = "polymarket", market_type = "f5_total" }
max_rows = 5
expires = 2099-01-01
'''


def _gate_run(tmp_path, a_lines, b_lines, waiver_text, today):
    import datetime
    from regression.diff import run
    a = _write(tmp_path, "a.jsonl", a_lines)
    b = _write(tmp_path, "b.jsonl", b_lines)
    w = tmp_path / "waivers.toml"
    w.write_text(waiver_text)
    out = io.StringIO()
    code = run(a, b, out=out, waivers_path=w,
               today=datetime.date(2026, 8, 12))
    return code, out.getvalue()


def test_gate_waived_delta_passes(tmp_path):
    base = [_canon("wnba", "kalshi", "point_spread", "T1")]
    added = base + [_canon("mlb", "polymarket", "f5_total", "T2")]
    # expiry within 90 days of the injected today
    waiver = GATE_WAIVER.replace("2099-01-01", "2026-09-01")
    code, text = _gate_run(tmp_path, base, added, waiver, "2026-08-12")
    assert code == 0
    assert "WAIVED wnba-kalshi-spread: 1/5" in text
    assert "GATE PASS" in text


def test_gate_unexplained_delta_fails(tmp_path):
    base = [_canon("wnba", "kalshi", "point_spread", "T1")]
    added = base + [_canon("epl", "kalshi", "moneyline", "T3")]
    waiver = GATE_WAIVER.replace("2099-01-01", "2026-09-01")
    code, text = _gate_run(tmp_path, base, added, waiver, "2026-08-12")
    assert code == 1
    assert "GATE FAIL: 1 unexplained" in text
    assert "stale waivers" in text  # the waiver matched nothing


def test_gate_identical_reports_stale_and_passes(tmp_path):
    base = [_canon("wnba", "kalshi", "point_spread", "T1")]
    waiver = GATE_WAIVER.replace("2099-01-01", "2026-09-01")
    code, text = _gate_run(tmp_path, base, base, waiver, "2026-08-12")
    assert code == 0
    assert "IDENTICAL" in text and "stale waivers" in text


def test_gate_invalid_waivers_raises(tmp_path):
    import pytest
    from regression.waivers import WaiverError
    base = [_canon("wnba", "kalshi", "point_spread", "T1")]
    with pytest.raises(WaiverError):
        _gate_run(tmp_path, base, base, GATE_WAIVER, "2026-08-12")
