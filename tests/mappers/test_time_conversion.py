"""Tests for UTC→ET time conversion — to_et_str and to_date_str."""

import pytest

from mappers.shared import to_date_str, to_et_str


# === to_et_str ===

@pytest.mark.parametrize("utc, expected_et", [
    # UTC midnight = 7pm ET previous day (EST is UTC-5)
    ("2026-02-20T00:00:00Z",  "2026-02-19T19:00:00"),
    # Daytime UTC = same ET day
    ("2026-02-19T18:00:00Z",  "2026-02-19T13:00:00"),
    # 5am UTC = midnight ET, still same ET calendar day
    ("2026-02-20T05:00:00Z",  "2026-02-20T00:00:00"),
    # DST crossing: July is EDT (UTC-4), not EST (UTC-5)
    ("2026-07-15T00:00:00Z",  "2026-07-14T20:00:00"),
])
def test_to_et_str(utc, expected_et):
    assert to_et_str(utc) == expected_et


# === to_date_str(to_et_str(...)) — the combined pipeline ===

@pytest.mark.parametrize("utc, expected_date", [
    # The midnight-crossing gotcha: UTC midnight → previous ET date
    ("2026-02-20T00:00:00Z",  "2026-02-19"),
    # Normal daytime
    ("2026-02-19T18:00:00Z",  "2026-02-19"),
    # Boundary: 5am UTC = midnight ET = Feb 20
    ("2026-02-20T05:00:00Z",  "2026-02-20"),
])
def test_utc_to_et_date(utc, expected_date):
    assert to_date_str(to_et_str(utc)) == expected_date
