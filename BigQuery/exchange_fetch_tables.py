"""BigQuery table ids and load schemas for exchange fetch snapshots."""

from __future__ import annotations

from google.cloud import bigquery

DATASET = "raw_ingestion_us"

TABLES = {
    "optic": f"{DATASET}.optic_fetch_raw",
    "kalshi": f"{DATASET}.kalshi_fetch_raw",
    "polymarket": f"{DATASET}.polymarket_fetch_raw",
    "crypto": f"{DATASET}.crypto_fetch_raw",
    "novig": f"{DATASET}.novig_fetch_raw",
    "px_events": f"{DATASET}.px_events_fetch_raw",
    "px_markets": f"{DATASET}.px_markets_fetch_raw",
    "polymarket_usa": f"{DATASET}.polymarket_usa_fetch_raw",
    # SX Bet's whole /markets/active book (fetch/sxbet.py). Loaded with
    # CREATE_NEVER: the table is Terraform-owned (mm-infrastructure
    # sxbet_fetch_raw), a missing one is a skipped load, never an auto-create.
    "sxbet": f"{DATASET}.sxbet_fetch_raw",
    # Underdog's open single-leg catalogue (fetch/underdog.py), CREATE_NEVER as sxbet.
    "underdog": f"{DATASET}.underdog_fetch_raw",
    # STX (Ontario exchange) open-market catalogue and per-event rosters (fetch/stx.py), CREATE_NEVER as sxbet.
    "stx": f"{DATASET}.stx_fetch_raw",
    "stx_players": f"{DATASET}.stx_players_fetch_raw",
}

LOAD_SCHEMAS: dict[str, list[bigquery.SchemaField]] = {
    "optic": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("league_id", "STRING"),
        bigquery.SchemaField("game_id", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    "kalshi": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("series_prefix", "STRING"),
        bigquery.SchemaField("event_ticker", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    "polymarket": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("slug_prefix", "STRING"),
        bigquery.SchemaField("condition_id", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    "crypto": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("league", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    "novig": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("kind", "STRING"),
        bigquery.SchemaField("league", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    "px_events": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("tournament_id", "STRING"),
        bigquery.SchemaField("event_id", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    "px_markets": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("tournament_id", "STRING"),
        bigquery.SchemaField("market_id", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    # Mirrors mm-infrastructure schemas/raw_ingestion/polymarket_usa_fetch_raw.sql
    # ``inner_league`` holds the gateway's numeric league id (as text) since
    # 2026-10-14; it held the league's URL key before.
    "polymarket_usa": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("inner_league", "STRING"),
        bigquery.SchemaField("event_ticker", "STRING"),
        bigquery.SchemaField("market_id", "STRING"),
        bigquery.SchemaField("market_side_id", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    # Mirrors mm-infrastructure schemas/raw_ingestion/sxbet_fetch_raw.sql.
    "sxbet": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("league_id", "STRING"),
        bigquery.SchemaField("event_id", "STRING"),
        bigquery.SchemaField("market_hash", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    # Mirrors mm-infrastructure schemas/raw_ingestion/underdog_fetch_raw.sql.
    "underdog": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("series_ticker", "STRING"),
        bigquery.SchemaField("event_ticker", "STRING"),
        bigquery.SchemaField("ticker", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    # Mirror mm-infrastructure schemas/raw_ingestion/stx_fetch_raw.sql and stx_players_fetch_raw.sql.
    "stx": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("event_id", "STRING"),
        bigquery.SchemaField("market_id", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
    "stx_players": [
        bigquery.SchemaField("snapshot_id", "STRING"),
        bigquery.SchemaField("fetch_time", "TIMESTAMP"),
        bigquery.SchemaField("event_id", "STRING"),
        bigquery.SchemaField("data", "STRING"),
    ],
}
