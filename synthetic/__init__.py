"""Synthetic fixtures + mappings for un-covered Kalshi series.

Mints our own `opticodds_fixtures` rows and `market_mapping` (GREG) rows for
Kalshi markets that OpticOdds does not cover at all, so the leg gets an
`optic_fixture_id` and can be priced IN-PLAY off the Kalshi order book. See
`synthetic/README.md` and docs_workspace/proposals/2026-08-13-itf-synthetic-fixtures.md.
"""
