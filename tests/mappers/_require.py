"""Narrow optional LeagueConfig book fields for tests."""

from __future__ import annotations


def require[T](value: T | None) -> T:
    """Assert a tip-wired book config is present and return it as non-optional."""
    assert value is not None
    return value
