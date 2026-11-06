"""Runshop vendor market dictionary — TOML archive today, BigQuery target.

The live dictionary is ~14k rows in ``config/world_cup/runshop_markets.toml``.
That file is vendor reference data (id, market name, line value, selection,
sport_id), not mapping-tip content. Crosswalk rules in ``mapping_market_rules``
map Optic types onto these names; the dictionary itself is fetched separately.

Phase 7a stubs the BigQuery table and loader. Stamping still reads the TOML
path until a fetch job lands vendor rows in BQ and the mapper reads them.
"""

from __future__ import annotations

from pathlib import Path

from mappers.exchanges.runshop_crosswalk import RunshopMarket, load_runshop_markets

VENDOR_TABLE = "raw_ingestion_us.runshop_vendor_markets"
DEFAULT_MARKETS_PATH = Path("vendor/world_cup/runshop_markets.toml")


def load_vendor_markets(path: Path | None = None) -> list[RunshopMarket]:
    """Load the Runshop vendor dictionary from the archive TOML path."""
    return load_runshop_markets(path or DEFAULT_MARKETS_PATH)


def vendor_markets_available_in_bq() -> bool:
    """True when the vendor dictionary BQ table exists and is readable."""
    try:
        from BigQuery.client import ro_client

        client = ro_client()
        client.get_table(VENDOR_TABLE)
        return True
    except Exception:
        return False
