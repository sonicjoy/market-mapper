"""method_of_victory selection normalization — MMMapper (source of truth).

These golden vectors are pinned IDENTICALLY in the MMOpticOdds vendored copy
(services/priceservice/tests/test_selection_normalization.py). If you change
the method vocabulary or the ``augment_selection`` format, update BOTH.
"""

import pytest

from mappers.fight_props import (
    augment_selection,
    is_emittable_method,
    is_mergable_method,
    normalize_selection,
    parse_optic_mov_name,
)


def _optic_base_fn():
    """Lazy import: BigQuery.load_mappings pulls google.cloud at module top,
    which isn't installed in the lean local venv. The pure golden-vector tests
    below don't need it; the _optic_base wiring tests skip when it's absent
    (CI installs the runtime superset)."""
    pytest.importorskip("google.cloud.bigquery")
    from BigQuery.load_mappings import _optic_base

    return _optic_base


# --- golden vectors (must match the priceservice vendored copy) ---------------

def test_parse_optic_mov_name_golden():
    assert parse_optic_mov_name("Steven Asplund - KO/TKO/DQ") == "ko_tko_dq"
    assert parse_optic_mov_name("Steven Asplund - Decision") == "decision"
    assert parse_optic_mov_name("Steven Asplund - Submission") == "submission"
    # non-mergable / unparseable
    assert parse_optic_mov_name("Steven Asplund - KO/TKO") == "ko_tko"
    assert parse_optic_mov_name("Draw") == "draw"
    assert parse_optic_mov_name("garbage") is None
    assert parse_optic_mov_name("") is None


def test_augment_selection_golden():
    assert augment_selection("Steven Asplund", "ko_tko_dq") == "Steven Asplund - ko_tko_dq"
    assert augment_selection("  Steven Asplund  ", "decision") == "Steven Asplund - decision"


def test_normalize_selection_mov():
    assert normalize_selection(
        "mma", "method_of_victory", "Steven Asplund", "Steven Asplund - KO/TKO/DQ"
    ) == "Steven Asplund - ko_tko_dq"
    assert normalize_selection(
        "mma", "method_of_victory", "Steven Asplund", "Steven Asplund - Decision"
    ) == "Steven Asplund - decision"
    assert normalize_selection(
        "mma", "method_of_victory", "Steven Asplund", "Steven Asplund - KO/TKO"
    ) == "Steven Asplund - ko_tko"


def test_normalize_selection_noop_cases():
    # non-mov market -> unchanged
    assert normalize_selection("mma", "moneyline", "Steven Asplund", "x") == "Steven Asplund"
    # non-mma sport, same market_id -> unchanged
    assert normalize_selection(
        "basketball", "method_of_victory", "X", "X - Decision"
    ) == "X"
    # unparseable name -> unchanged
    assert normalize_selection("mma", "method_of_victory", "Steven Asplund", "") == "Steven Asplund"


def test_is_mergable_method():
    assert is_mergable_method("ko_tko_dq")
    assert is_mergable_method("submission")
    assert is_mergable_method("decision")
    assert not is_mergable_method("ko_tko")
    assert not is_mergable_method("draw")
    assert not is_mergable_method(None)


def test_is_emittable_method_includes_ko_tko():
    assert is_emittable_method("ko_tko_dq")
    assert is_emittable_method("ko_tko")
    assert not is_emittable_method("draw")
    assert not is_emittable_method(None)


# --- _optic_base: the GREG `selection` VALUE column gets augmented -------------

def _mov_key(**over):
    k = {
        "league": "ufc",
        "start_date": "2026-08-08T00:00:00+00:00",
        "home": "steven_asplund",
        "away": "opponent",
        "market_type": "method_of_victory",
        "entity": "steven_asplund",
        "line": None,
        "side": "yes",
        "grouping_key": "ko_tko_dq",  # canonical method -> group_key KEY column
    }
    k.update(over)
    return k


def _mov_optic(**over):
    o = {
        "game_id": "11127-29657-2026-08",
        "fixture_id": "202608084A0577BA",
        "market_id": "method_of_victory",
        "selection": "Steven Asplund",
        "selection_line": "",
        "points": 0.0,
        "grouping_key": "default",  # raw Optic passthrough
    }
    o.update(over)
    return o


def test_optic_base_augments_mov_selection():
    _optic_base = _optic_base_fn()
    row = _optic_base(_mov_key(), _mov_optic(), "2026-08-08T00:00:00+00:00")
    assert row["selection"] == "Steven Asplund - ko_tko_dq"
    # KEY column and identity fields are untouched
    assert row["group_key"] == "ko_tko_dq"
    assert row["entity"] == "steven_asplund"
    assert row["side"] == "yes"
    assert row["grouping_key"] == "default"  # raw passthrough VALUE column unchanged


def test_optic_base_decision_bucket():
    _optic_base = _optic_base_fn()
    row = _optic_base(_mov_key(grouping_key="decision"), _mov_optic(), "t")
    assert row["selection"] == "Steven Asplund - decision"
    assert row["group_key"] == "decision"


def test_optic_base_non_mov_unchanged():
    _optic_base = _optic_base_fn()
    k = _mov_key(market_type="moneyline", grouping_key=None)
    o = _mov_optic(market_id="moneyline", selection="Steven Asplund")
    row = _optic_base(k, o, "t")
    assert row["selection"] == "Steven Asplund"
    assert row["group_key"] is None
