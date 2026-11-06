"""Tests for normalize_line — safe float equality for betting lines."""

from mappers.shared import normalize_line


def test_none():
    assert normalize_line(None) is None


def test_integers():
    assert normalize_line(2) == 2
    assert normalize_line(220) == 220


def test_half_points():
    assert normalize_line(2.5) == 2.5
    assert normalize_line(220.5) == 220.5


def test_quarter_points():
    assert normalize_line(2.25) == 2.25
    assert normalize_line(2.75) == 2.75
    assert normalize_line(107.25) == 107.25


def test_arithmetic_drift():
    """The case this actually guards against."""
    drifted = 220.5 + 1e-13  # simulated drift
    assert drifted != 220.5       # broken without normalize
    assert normalize_line(drifted) == 220.5  # fixed


def test_int_float_equivalence():
    """Python guarantees hash(2) == hash(2.0), but worth documenting."""
    assert normalize_line(2) == normalize_line(2.0)
