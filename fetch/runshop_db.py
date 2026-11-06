"""Postgres helpers for Runshop fixture chain enrichment."""

from __future__ import annotations

import ssl

import pg8000.native

TX_HOST = "35.242.130.72"
TX_DATABASE = "txodds-fusion"
TX_USER = "markets_reader"

POLY_HOST = "34.39.52.158"
POLY_DATABASE = "polymarket"
POLY_USER = "spyridon"

_BATCH_SIZE = 500


def _tx_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def connect_tx(password: str) -> pg8000.native.Connection:
    return pg8000.native.Connection(
        TX_USER,
        host=TX_HOST,
        password=password,
        database=TX_DATABASE,
        timeout=60,
        ssl_context=_tx_ssl_context(),
    )


def connect_poly(password: str) -> pg8000.native.Connection:
    return pg8000.native.Connection(
        POLY_USER,
        host=POLY_HOST,
        password=password,
        database=POLY_DATABASE,
        timeout=60,
    )


def _iter_rows(result) -> list:
    if result is None:
        return []
    return list(result)


def fetch_tx_legacy_by_fixture_ids(
    tx_con: pg8000.native.Connection,
    fixture_ids: list[int],
) -> dict[int, int]:
    """Map tx live fixture_id → legacy_fixture_id."""
    if not fixture_ids:
        return {}
    out: dict[int, int] = {}
    for start in range(0, len(fixture_ids), _BATCH_SIZE):
        batch = fixture_ids[start:start + _BATCH_SIZE]
        in_list = ",".join(str(int(x)) for x in batch)
        rows = _iter_rows(tx_con.run(
            "select fixture_id, legacy_fixture_id "
            "from public.fixture "
            f"where fixture_id in ({in_list}) "
            "and legacy_fixture_id is not null",
        ))
        for fixture_id, legacy_id in rows:
            if legacy_id is None:
                continue
            out[int(fixture_id)] = int(legacy_id)
    return out


def fetch_poly_by_legacy_ids(
    poly_con: pg8000.native.Connection,
    legacy_ids: list[int],
) -> dict[int, str]:
    if not legacy_ids:
        return {}
    out: dict[int, str] = {}
    for start in range(0, len(legacy_ids), _BATCH_SIZE):
        batch = legacy_ids[start:start + _BATCH_SIZE]
        in_list = ",".join(str(int(x)) for x in batch)
        rows = _iter_rows(poly_con.run(
            "select tx_legacy_fixture_id, game_id "
            "from poly_tx_mapping.fixtures "
            f"where tx_legacy_fixture_id in ({in_list})",
        ))
        for legacy_id, game_id in rows:
            out[int(legacy_id)] = str(game_id)
    return out


def fetch_events(
    poly_con: pg8000.native.Connection,
    game_ids: set[str],
) -> dict[str, tuple[str | None, str | None]]:
    if not game_ids:
        return {}
    events: dict[str, tuple[str | None, str | None]] = {}
    ids = sorted(game_ids)
    for start in range(0, len(ids), _BATCH_SIZE):
        batch = ids[start:start + _BATCH_SIZE]
        in_list = ",".join(
            "'" + gid.replace("'", "''") + "'" for gid in batch
        )
        rows = _iter_rows(poly_con.run(
            "select game_id, title, start_time "
            "from public.events "
            f"where game_id in ({in_list})",
        ))
        for game_id, title, start_time in rows:
            gid = str(game_id)
            if gid in events:
                continue
            events[gid] = (
                title,
                str(start_time) if start_time else None,
            )
    return events
