"""Polymarket harvest BQ helpers (injected query_fn; no live BQ)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.gap_fix_poly_bq import (
    _US_CLOSE_EVENTS_SQL,
    _US_EVENTS_SQL,
    fetch_close_us_events,
    fetch_optic_window,
    fetch_poly_official_events,
    fetch_poly_us_events,
    optic_rows_from_cache,
    persist_us_events_ttl,
)
from mappers.control_plane.gap_harvest_ttl import (
    POLY_US_EVENTS,
    load_ttl,
    save_dead_buckets,
    save_ttl,
)
from tests.control_plane.gap_store_helpers import _store
from tests.control_plane.test_gap_fix import _poly_us_league

_UFC_SYM = "aec-ufc-ryagan-ozzdia-2026-09-19"


def _gw_event(
    eid: str, teams: list[tuple[str, str]], start: str, slugs: list[str],
) -> dict[str, Any]:
    """A gateway ``/v2/leagues/{inner}/events`` row with nested markets."""
    return {
        "id": eid,
        "startTime": start,
        "teams": [
            {"id": f"{eid}-{i}", "abbreviation": abbr, "name": name}
            for i, (abbr, name) in enumerate(teams)
        ],
        "markets": [{"id": f"{eid}-m{i}", "slug": slug} for i, slug in enumerate(slugs)],
    }


def _ufc_events(us_league_events: dict[str, list[dict[str, Any]]]) -> None:
    us_league_events["ufc"] = [_gw_event(
        "e1", [("ryagan", "Ryan Gandra"), ("ozzdia", "Ozzy Diaz")],
        "2026-09-19T23:00:00Z", [_UFC_SYM, f"{_UFC_SYM}-ryagan"],
    )]


def test_fetch_poly_official_events_filters_and_dedupes() -> None:
    rows = [
        {"prefix": "ja2", "question": "Jubilo vs Kataller", "d": "2026-09-06"},
        {"prefix": "ja2", "question": "Jubilo vs Kataller", "d": "2026-09-06"},
        {"prefix": "cfb", "question": "Alabama vs Auburn", "d": "2026-09-01"},
    ]
    out = fetch_poly_official_events(["ja2"], query_fn=lambda _sql: rows)
    assert out == [
        {"prefix": "ja2", "question": "Jubilo vs Kataller", "date": "2026-09-06"},
    ]


def test_fetch_poly_official_events_copies_slug_and_outcome() -> None:
    rows = [
        {
            "prefix": "bun",
            "question": "RB Leipzig vs. Gladbach: O/U 2.5",
            "d": "2026-08-29",
            "slug": "bun-lei-moe-2026-08-29-total-2pt5",
            "outcome_label": "Over",
        },
    ]
    out = fetch_poly_official_events(["bun"], query_fn=lambda _sql: rows)
    assert out == [
        {
            "prefix": "bun",
            "question": "RB Leipzig vs. Gladbach: O/U 2.5",
            "date": "2026-08-29",
            "slug": "bun-lei-moe-2026-08-29-total-2pt5",
            "outcome_label": "Over",
        },
    ]


def test_fetch_poly_official_events_empty_prefixes() -> None:
    assert fetch_poly_official_events([], query_fn=lambda _sql: [{"prefix": "ja2"}]) == []


def test_fetch_poly_us_events_reuses_ttl(monkeypatch: Any) -> None:
    save_ttl(
        POLY_US_EVENTS,
        {
            "prefixes": ["mlb", "nfl"],
            "events": [
                {"inner": "mlb", "ticker": "mlb-a"},
                {"inner": "nfl", "ticker": "nfl-a"},
            ],
        },
    )

    def boom(*_a: object, **_k: object) -> list[object]:
        raise RuntimeError("bq should not run")

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "mappers.control_plane.gap_fix_poly_bq._query", boom,
    )
    out = fetch_poly_us_events(["mlb"])
    assert out == [{"inner": "mlb", "ticker": "mlb-a"}]


def test_fetch_poly_us_events_unions_new_prefix(
    monkeypatch: Any, us_league_events: dict[str, list[dict[str, Any]]],
) -> None:
    save_ttl(
        POLY_US_EVENTS,
        {"prefixes": ["mlb"], "events": [{"inner": "mlb", "ticker": "mlb-a", "title": "cached"}]},
    )
    sym = "some-opaque-nfl-symbol"
    us_league_events["nfl"] = [_gw_event(
        "n1", [("nyg", "New York Giants"), ("dal", "Dallas Cowboys")],
        "2026-09-11T00:20:00Z", [sym],
    )]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "mappers.control_plane.gap_fix_poly_bq._query",
        lambda _p, _sql, **_k: [{"symbol": sym}],
    )
    out = fetch_poly_us_events(["mlb", "nfl"])
    by_inner = {row["inner"]: row for row in out}
    assert by_inner["mlb"]["title"] == "cached"
    assert by_inner["nfl"]["ticker"] == sym
    assert by_inner["nfl"]["title"] == "New York Giants vs Dallas Cowboys"
    blob = load_ttl(POLY_US_EVENTS)
    assert set(blob["prefixes"]) == {"mlb", "nfl"}
    persist_us_events_ttl(out)
    again = fetch_poly_us_events(["mlb"])
    assert again[0]["title"] == "cached"


def test_fetch_poly_official_sql_binds_prefixes() -> None:
    captured: list[str] = []

    def query_fn(sql: str) -> list[object]:
        captured.append(sql)
        return []

    fetch_poly_official_events(["ja2", "bun"], query_fn=query_fn)
    assert captured
    assert "unnest(@prefixes)" in captured[0]


def test_us_sql_never_splits_the_symbol() -> None:
    for sql in (_US_EVENTS_SQL, _US_CLOSE_EVENTS_SQL):
        assert "split(" not in sql
        assert "select distinct" in sql.casefold()
        assert "as symbol" in sql


def test_fetch_optic_window_filters_leagues() -> None:
    captured: list[str] = []

    def query_fn(sql: str) -> list[object]:
        captured.append(sql)
        return []

    fetch_optic_window(query_fn=query_fn, optic_ids=["ncaaf"])
    fetch_optic_window(query_fn=query_fn)
    assert "unnest(@optic_ids)" in captured[0]
    assert "unnest(@optic_ids)" not in captured[1]
    assert fetch_optic_window(query_fn=query_fn, optic_ids=[]) == []
    assert len(captured) == 2


def test_fetch_poly_official_skips_ttl_prefixes() -> None:
    save_dead_buckets("polymarket", {"ja2"})
    called: list[str] = []

    def query_fn(sql: str) -> list[dict[str, str]]:
        called.append(sql)
        return [{"prefix": "ja2", "question": "Jubilo vs Kataller", "d": "2026-09-06"}]

    assert fetch_poly_official_events(["ja2"], query_fn=query_fn) == []
    assert called == []


def test_close_sql_includes_horizon_blocked() -> None:
    assert "select distinct" in _US_CLOSE_EVENTS_SQL.casefold()
    assert "interval 24 hour" in _US_CLOSE_EVENTS_SQL
    assert "first_publish_time" in _US_CLOSE_EVENTS_SQL
    assert "{publish_days} day" in _US_CLOSE_EVENTS_SQL
    assert "UNMAPPED" not in _US_CLOSE_EVENTS_SQL
    assert "MAPPING_FAILED" not in _US_CLOSE_EVENTS_SQL
    assert "interval 48 hour" not in _US_CLOSE_EVENTS_SQL


def test_fetch_close_us_events_one_row_per_gateway_event(
    us_league_events: dict[str, list[dict[str, Any]]],
) -> None:
    _ufc_events(us_league_events)

    def rows() -> Any:
        yield {"symbol": _UFC_SYM}
        yield {"symbol": f"{_UFC_SYM}-ryagan"}
        yield {"symbol": "atc-kor-seo-uls-2026-08-29"}

    out = fetch_close_us_events(["ufc"], query_fn=lambda _sql: rows())
    assert out == [
        {
            "inner": "ufc",
            "home": "ryagan",
            "away": "ozzdia",
            "date": "2026-09-19",
            "start": "2026-09-19T23:00:00Z",
            "ticker": _UFC_SYM,
            "title": "Ryan Gandra vs Ozzy Diaz",
            "team_names": {"ryagan": "Ryan Gandra", "ozzdia": "Ozzy Diaz"},
        },
    ]


def test_fetch_close_us_events_ignores_symbols_the_gateway_does_not_list(
    us_league_events: dict[str, list[dict[str, Any]]],
) -> None:
    """A symbol-shaped string is nothing until the gateway lists it."""
    _ufc_events(us_league_events)
    rows = [{"symbol": "aec-ufc-abc-def-2026-09-19"}]
    assert fetch_close_us_events(["ufc"], query_fn=lambda _sql: rows) == []


def test_optic_rows_from_cache_tags_league_and_extra_ids(monkeypatch: Any) -> None:
    def fake_cache(oid: str, *, horizon_hours: float = 96.0) -> list[dict[str, Any]]:
        _ = horizon_hours
        if oid == "ufc":
            return [{"id": "fx-ufc"}]
        if oid == "ufc_alt":
            return [{"id": "fx-alt"}]
        return []

    monkeypatch.setattr(
        "mappers.control_plane.gap_fix_poly_bq.cached_optic_fixtures",
        fake_cache,
    )
    league = _poly_us_league("ufc", "ufc", "ufc", sport="mma")
    league.extra_optic_league_ids = ["ufc_alt"]
    store = _store([], [league])
    rows = optic_rows_from_cache(store, ["ufc"])
    assert [row["optic_league_id"] for row in rows] == ["ufc", "ufc_alt"]
    assert [row["id"] for row in rows] == ["fx-ufc", "fx-alt"]


def test_fetch_close_us_events_does_not_use_ttl() -> None:
    calls = {"n": 0}

    def query(_sql: str) -> list[dict[str, str]]:
        calls["n"] += 1
        return [{"symbol": _UFC_SYM}]

    fetch_close_us_events(["ufc"], query_fn=query)
    fetch_close_us_events(["ufc"], query_fn=query)
    assert calls["n"] == 2
