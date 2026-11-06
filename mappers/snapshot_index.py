"""In-memory league-keyed fetch snapshot for mapping."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from BigQuery.exchange_fetch_extract import (
    kalshi_keys,
    polymarket_keys,
    polymarket_usa_keys,
)
from BigQuery.exchange_fetch_snapshot import (
    fetch_time_from_dir,
    fetch_time_from_snapshot_id,
    fetch_time_window,
    snapshot_id_from_dir,
)
from BigQuery.exchange_fetch_tables import TABLES
from mappers.exchanges.novig import novig_league_key
from mappers.shared import lines, lines_if_exists

# Every hydrate read is a point-read on snapshot_id, but snapshot_id prunes
# nothing on its own: the *_fetch_raw tables are wide and append-only, so a
# bare `WHERE snapshot_id = ...` scans every daily partition.  The fetch_time
# band (see fetch_time_window: ± one mapper tick) pins DATE(fetch_time) to
# one partition, two if the tick sits on UTC midnight.  Clustering on
# snapshot_id then prunes inside that partition.  fetch_time equals the
# instant snapshot_id names, so the band excludes nothing today.
# The `{table}` placeholder is filled from the TABLES constant, never from
# input; snapshot_id and the fetch_time bounds are bound query parameters.
# Written out per source rather than composed, so these stay plain literals.
_HYDRATE_SQL = {
    "optic": (
        "SELECT league_id, data FROM `{table}` "
        "WHERE fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi "
        "AND snapshot_id = @snapshot_id"
    ),
    "kalshi": (
        "SELECT event_ticker, data FROM `{table}` "
        "WHERE fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi "
        "AND snapshot_id = @snapshot_id"
    ),
    "polymarket": (
        "SELECT data FROM `{table}` "
        "WHERE fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi "
        "AND snapshot_id = @snapshot_id"
    ),
    "crypto": (
        "SELECT league, data FROM `{table}` "
        "WHERE fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi "
        "AND snapshot_id = @snapshot_id"
    ),
    "novig": (
        "SELECT kind, league, data FROM `{table}` "
        "WHERE fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi "
        "AND snapshot_id = @snapshot_id"
    ),
    "px_events": (
        "SELECT tournament_id, data FROM `{table}` "
        "WHERE fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi "
        "AND snapshot_id = @snapshot_id"
    ),
    "px_markets": (
        "SELECT tournament_id, data FROM `{table}` "
        "WHERE fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi "
        "AND snapshot_id = @snapshot_id"
    ),
    # One row per market SIDE (both sides carry the same market line).
    "polymarket_usa": (
        "SELECT DISTINCT data FROM `{table}` "
        "WHERE fetch_time BETWEEN @fetch_time_lo AND @fetch_time_hi "
        "AND snapshot_id = @snapshot_id"
    ),
}


@dataclass
class SnapshotIndex:
    """Once-per-tick in-memory KV over fetch lines."""

    snapshot_id: str
    fetch_time: datetime
    optic_by_league: dict[str, list[str]] = field(default_factory=dict)
    kalshi_lines: list[str] = field(default_factory=list)
    kalshi_by_sport: dict[str, list[str]] = field(default_factory=dict)
    polymarket_lines: list[str] = field(default_factory=list)
    poly_by_prefix: dict[str, list[str]] = field(default_factory=dict)
    polymarket_usa_markets: list[str] = field(default_factory=list)
    poly_usa_by_league: dict[str, list[str]] = field(default_factory=dict)
    crypto_by_league: dict[str, list[str]] = field(default_factory=dict)
    novig_events_by_league: dict[str, list[str]] = field(default_factory=dict)
    novig_markets_by_league: dict[str, list[str]] = field(default_factory=dict)
    px_events_by_tournament: dict[str, list[str]] = field(default_factory=dict)
    px_markets_by_tournament: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_jsonl(cls, data_dir: Path) -> SnapshotIndex:
        """Build index from local JSONL (tests / fallback)."""
        idx = cls(
            snapshot_id=snapshot_id_from_dir(data_dir),
            fetch_time=fetch_time_from_dir(data_dir),
        )
        idx._ingest_jsonl(data_dir)
        return idx

    def _add_kalshi_line(self, line: str) -> None:
        self.kalshi_lines.append(line)
        sport, _event_ticker = kalshi_keys(line)
        if sport:
            self.kalshi_by_sport.setdefault(sport, []).append(line)

    def _add_poly_line(self, line: str) -> None:
        self.polymarket_lines.append(line)
        head, _cond = polymarket_keys(line)
        if head:
            self.poly_by_prefix.setdefault(head, []).append(line)

    @classmethod
    def hydrate(cls, snapshot_id: str, project: str) -> SnapshotIndex:
        """Load snapshot rows from BigQuery."""
        client = bigquery.Client(project=project)
        fts = fetch_time_from_snapshot_id(snapshot_id)
        idx = cls(snapshot_id=snapshot_id, fetch_time=fts)
        idx._ingest_bq(client)
        return idx

    def _ingest_jsonl(self, data_dir: Path) -> None:
        self._load_optic(data_dir / "optic_fixtures_odds.jsonl")
        self._load_kalshi(data_dir / "kalshi_markets.jsonl")
        self._load_poly(data_dir / "polymarket_markets.jsonl")
        self._load_poly_usa(data_dir / "polymarket_usa_markets.jsonl")
        self._load_crypto(data_dir / "crypto_com_markets.jsonl")
        self._load_novig(data_dir)
        self._load_px(data_dir)

    def _load_optic(self, path: Path) -> None:
        if not path.exists():
            return
        for line in lines(path):
            obj = json.loads(line)
            league = (obj.get("league") or {}).get("id")
            if league is None:
                continue
            self.optic_by_league.setdefault(str(league), []).append(line)

    def _load_kalshi(self, path: Path) -> None:
        if not path.exists():
            return
        for line in lines(path):
            self._add_kalshi_line(line)

    def _load_poly(self, path: Path) -> None:
        if not path.exists():
            return
        for line in lines(path):
            self._add_poly_line(line)

    def _load_poly_usa(self, path: Path) -> None:
        if not path.exists():
            return
        for line in lines(path):
            self._add_poly_usa_line(line)

    def _add_poly_usa_line(self, line: str) -> None:
        self.polymarket_usa_markets.append(line)
        league, _event, _market = polymarket_usa_keys(line)
        if league:
            self.poly_usa_by_league.setdefault(league, []).append(line)

    def _load_crypto(self, path: Path) -> None:
        if not path.exists():
            return
        for line in lines(path):
            obj = json.loads(line)
            league = obj.get("league") or obj.get("eventMetaLEAGUE")
            if league is None:
                continue
            self.crypto_by_league.setdefault(str(league), []).append(line)

    def _load_novig(self, data_dir: Path) -> None:
        for _kind, fname, bucket in (
            ("events", "novig_events.jsonl", self.novig_events_by_league),
            ("markets", "novig_markets.jsonl", self.novig_markets_by_league),
        ):
            path = data_dir / fname
            if not path.exists():
                continue
            for line in lines(path):
                league = json.loads(line).get("league")
                if league is None:
                    continue
                bucket.setdefault(novig_league_key(str(league)), []).append(line)

    def _load_px(self, data_dir: Path) -> None:
        event_to_tid: dict[str, str] = {}
        ev_path = data_dir / "prophetx_events.jsonl"
        if ev_path.exists():
            for line in lines(ev_path):
                obj = json.loads(line)
                tid = obj.get("tournament_id")
                if tid is None:
                    continue
                tid_s = str(tid)
                self.px_events_by_tournament.setdefault(tid_s, []).append(line)
                eid = obj.get("id") or obj.get("event_id")
                if eid is not None:
                    event_to_tid[str(eid)] = tid_s
        mk_path = data_dir / "prophetx_markets.jsonl"
        if not mk_path.exists():
            return
        for line in lines(mk_path):
            obj = json.loads(line)
            tid = obj.get("tournament_id")
            if tid is None:
                eid = obj.get("sport_event_id") or obj.get("event_id")
                tid = event_to_tid.get(str(eid)) if eid is not None else None
            if tid is not None:
                self.px_markets_by_tournament.setdefault(str(tid), []).append(line)

    def _ingest_bq(self, client: bigquery.Client) -> None:
        lo, hi = fetch_time_window(self.fetch_time)
        params = [
            bigquery.ScalarQueryParameter("snapshot_id", "STRING", self.snapshot_id),
            bigquery.ScalarQueryParameter("fetch_time_lo", "TIMESTAMP", lo),
            bigquery.ScalarQueryParameter("fetch_time_hi", "TIMESTAMP", hi),
        ]
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        self._bq_optic(client, job_config)
        self._bq_kalshi(client, job_config)
        self._bq_poly(client, job_config)
        self._bq_poly_usa(client, job_config)
        self._bq_crypto(client, job_config)
        self._bq_novig(client, job_config)
        self._bq_px(client, job_config)

    def _bq_optic(self, client: bigquery.Client, cfg: bigquery.QueryJobConfig) -> None:
        sql = _HYDRATE_SQL["optic"].format(table=TABLES["optic"])
        for row in client.query(sql, job_config=cfg).result():
            lid = row.league_id
            if lid:
                self.optic_by_league.setdefault(str(lid), []).append(row.data)

    def _bq_kalshi(self, client: bigquery.Client, cfg: bigquery.QueryJobConfig) -> None:
        sql = _HYDRATE_SQL["kalshi"].format(table=TABLES["kalshi"])
        for row in client.query(sql, job_config=cfg).result():
            self._add_kalshi_line(row.data)

    def _bq_poly(self, client: bigquery.Client, cfg: bigquery.QueryJobConfig) -> None:
        sql = _HYDRATE_SQL["polymarket"].format(table=TABLES["polymarket"])
        for row in client.query(sql, job_config=cfg).result():
            self._add_poly_line(row.data)

    def _bq_poly_usa(self, client: bigquery.Client, cfg: bigquery.QueryJobConfig) -> None:
        sql = _HYDRATE_SQL["polymarket_usa"].format(table=TABLES["polymarket_usa"])
        try:
            rows = client.query(sql, job_config=cfg).result()
        except NotFound:
            return
        for row in rows:
            self._add_poly_usa_line(row.data)

    def _bq_crypto(self, client: bigquery.Client, cfg: bigquery.QueryJobConfig) -> None:
        sql = _HYDRATE_SQL["crypto"].format(table=TABLES["crypto"])
        for row in client.query(sql, job_config=cfg).result():
            if row.league:
                self.crypto_by_league.setdefault(str(row.league), []).append(row.data)

    def _bq_novig(self, client: bigquery.Client, cfg: bigquery.QueryJobConfig) -> None:
        sql = _HYDRATE_SQL["novig"].format(table=TABLES["novig"])
        for row in client.query(sql, job_config=cfg).result():
            bucket = (
                self.novig_events_by_league if row.kind == "events"
                else self.novig_markets_by_league
            )
            if row.league:
                bucket.setdefault(novig_league_key(str(row.league)), []).append(row.data)

    def _bq_px(self, client: bigquery.Client, cfg: bigquery.QueryJobConfig) -> None:
        event_to_tid: dict[str, str] = {}
        sql = _HYDRATE_SQL["px_events"].format(table=TABLES["px_events"])
        for row in client.query(sql, job_config=cfg).result():
            if not row.tournament_id:
                continue
            tid = str(row.tournament_id)
            self.px_events_by_tournament.setdefault(tid, []).append(row.data)
            obj = json.loads(row.data)
            eid = obj.get("id") or obj.get("event_id")
            if eid is not None:
                event_to_tid[str(eid)] = tid
        sql = _HYDRATE_SQL["px_markets"].format(table=TABLES["px_markets"])
        for row in client.query(sql, job_config=cfg).result():
            tid = str(row.tournament_id) if row.tournament_id else None
            if tid is None:
                obj = json.loads(row.data)
                eid = obj.get("sport_event_id") or obj.get("event_id")
                tid = event_to_tid.get(str(eid)) if eid is not None else None
            if tid:
                self.px_markets_by_tournament.setdefault(tid, []).append(row.data)

    def optic_lines(self, league_id: str, extra: Iterable[str] = ()) -> list[str]:
        ids = {league_id, *extra}
        out: list[str] = []
        for lid in ids:
            out.extend(self.optic_by_league.get(lid, ()))
        return out

    def kalshi_lines_for_sport(self, sport: str) -> list[str]:
        return list(self.kalshi_by_sport.get(sport, ()))

    def polymarket_lines_for_prefix(self, slug_prefix: str) -> list[str]:
        needle = f"{slug_prefix}-"
        out: list[str] = []
        for line in self.poly_by_prefix.get(slug_prefix, ()):
            slug = json.loads(line).get("slug") or ""
            # legacy: ticker parse — replace with the typed venue field, do not extend
            if str(slug).startswith(needle):
                out.append(line)
        return out

    def polymarket_usa_markets_for_leagues(self, league_ids: frozenset[int]) -> list[str]:
        return [
            line for lid in sorted(league_ids)
            for line in self.poly_usa_by_league.get(str(lid), ())
        ]

    def crypto_lines(self, league: str) -> list[str]:
        return list(self.crypto_by_league.get(league, ()))

    def novig_event_lines(self, league: str) -> list[str]:
        return list(self.novig_events_by_league.get(novig_league_key(league), ()))

    def novig_market_lines(self, league: str) -> list[str]:
        return list(self.novig_markets_by_league.get(novig_league_key(league), ()))

    def px_event_lines(self, tournament_id: str) -> list[str]:
        return list(self.px_events_by_tournament.get(str(tournament_id), ()))

    def px_market_lines(self, tournament_id: str) -> list[str]:
        return list(self.px_markets_by_tournament.get(str(tournament_id), ()))


def snapshot_source_mode() -> str:
    return os.environ.get("MAP_SNAPSHOT_SOURCE", "jsonl").strip().lower()


def _index_from_jsonl(data_dir: Path) -> SnapshotIndex | None:
    try:
        idx = SnapshotIndex.from_jsonl(data_dir)
        print(
            f"  snapshot indexed: {idx.snapshot_id} "
            f"(optic leagues={len(idx.optic_by_league)}, "
            f"kalshi={len(idx.kalshi_lines)})",
            file=sys.stderr,
        )
        return idx
    except ValueError:
        return None
    except Exception as exc:
        print(f"ALERT: JSONL snapshot index failed: {exc}", file=sys.stderr)
        return None


def _hydrate_from_bq(data_dir: Path) -> SnapshotIndex | None:
    snap_id = snapshot_id_from_dir(data_dir)
    project = os.environ.get("GCP_PROJECT", "")
    if not project:
        print("ALERT: MAP_SNAPSHOT_SOURCE=bq but GCP_PROJECT unset",
              file=sys.stderr)
        return None
    try:
        idx = SnapshotIndex.hydrate(snap_id, project)
        print(f"  snapshot hydrated: {snap_id} "
              f"(optic leagues={len(idx.optic_by_league)}, "
              f"kalshi={len(idx.kalshi_lines)})", file=sys.stderr)
        return idx
    except Exception as exc:
        print(f"ALERT: BQ snapshot hydrate failed ({snap_id}): {exc}",
              file=sys.stderr)
        return None


def resolve_snapshot(data_dir: Path) -> SnapshotIndex | None:
    """Once-per-tick in-memory KV from JSONL; BQ hydrate if MAP_SNAPSHOT_SOURCE=bq."""
    if snapshot_source_mode() == "bq":
        idx = _hydrate_from_bq(data_dir)
        if idx is not None:
            return idx
    return _index_from_jsonl(data_dir)


def filter_empty_optic(
    snapshot: SnapshotIndex | None,
    keys: list[str],
    leagues: Mapping[str, Any],
) -> list[str]:
    """Drop leagues with no Optic fixtures when the snapshot has any."""
    if snapshot is None or not snapshot.optic_by_league or len(keys) <= 1:
        return keys
    kept: list[str] = []
    for key in keys:
        optic = leagues[key].OPTIC
        if snapshot.optic_lines(optic.league_id, optic.extra_league_ids):
            kept.append(key)
            continue
        print(f"skip: {key} no optic fixtures", file=sys.stderr)
    return kept


_WORKER_SNAPSHOT: SnapshotIndex | None = None


def worker_init(snapshot: SnapshotIndex | None) -> None:
    """ProcessPoolExecutor initializer — share SnapshotIndex via fork COW."""
    global _WORKER_SNAPSHOT
    _WORKER_SNAPSHOT = snapshot


def worker_snapshot() -> SnapshotIndex | None:
    return _WORKER_SNAPSHOT


def iter_file_or_snapshot(
    path: Path,
    snapshot_lines: list[str] | None,
    *,
    missing_label: str | None = None,
) -> Iterator[str]:
    """Yield lines from snapshot slice or fall back to file."""
    if snapshot_lines is not None:
        yield from snapshot_lines
        return
    if missing_label and not path.exists():
        print(f"  {missing_label} not found — skipping", file=sys.stderr)
        return
    yield from lines_if_exists(path)
