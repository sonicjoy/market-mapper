"""Known fixture_source values for mapping_leagues rows.

Kept free of the ``synthetic`` package so the control-plane app can import
without shipping the Kalshi synthetic-fixture job into the console image.
"""

from __future__ import annotations

FIXTURE_SOURCE_API = "api"
FIXTURE_SOURCE_BQ = "bq"
FIXTURE_SOURCE_SYNTHETIC = "synthetic"

KNOWN_FIXTURE_SOURCES = frozenset(
    {FIXTURE_SOURCE_API, FIXTURE_SOURCE_BQ, FIXTURE_SOURCE_SYNTHETIC}
)
