"""Batch crypto_security_def catalogue lookups."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from mappers.control_plane.gap_crypto_catalogue import (
    batched_catalogue_fn,
    prefetch_crypto_catalogue,
)


def test_prefetch_prefers_exact_symbol_over_base() -> None:
    exact = _row("NX.F.OPT.UFC-1.20260822", "NX.F.OPT.UFC-1", "exact", datetime(2026, 8, 1, tzinfo=UTC))
    base = _row("NX.F.OPT.UFC-1", "NX.F.OPT.UFC-1", "base", datetime(2026, 8, 2, tzinfo=UTC))
    out = prefetch_crypto_catalogue(
        ["NX.F.OPT.UFC-1.20260822"],
        query_fn=lambda syms: _select([base, exact], syms),
    )
    assert out["NX.F.OPT.UFC-1.20260822"]["meta_name"] == "exact"
    assert out["NX.F.OPT.UFC-1.20260822"]["seen"] is True


def test_prefetch_falls_back_to_maturity_base() -> None:
    base = _row("NX.F.OPT.UFC-1", "NX.F.OPT.UFC-1", "base", datetime(2026, 8, 2, tzinfo=UTC))
    out = prefetch_crypto_catalogue(
        ["NX.F.OPT.UFC-1.20260822"],
        query_fn=lambda syms: _select([base], syms),
    )
    assert out["NX.F.OPT.UFC-1.20260822"]["meta_name"] == "base"


def test_prefetch_miss_is_soft() -> None:
    out = prefetch_crypto_catalogue(["NX.F.OPT.UFC-1"], query_fn=lambda *_a: [])
    assert out["NX.F.OPT.UFC-1"] == {"ok": True, "seen": False, "symbol": "NX.F.OPT.UFC-1"}


def test_null_publish_time_does_not_crash_assignment() -> None:
    """A NULL publish_time next to a TIMESTAMP must not raise from _assign_rows."""
    dated = _row("NX.F.OPT.UFC-1.20260822", "NX.F.OPT.UFC-1", "dated", datetime(2026, 8, 1, tzinfo=UTC))
    undated = _row("NX.F.OPT.UFC-1", "NX.F.OPT.UFC-1", "undated", None)
    out = prefetch_crypto_catalogue(
        ["NX.F.OPT.UFC-1.20260915"],
        query_fn=lambda syms: _select([undated, dated], syms),
    )
    assert out["NX.F.OPT.UFC-1.20260915"]["meta_name"] == "undated"


def test_batched_fn_none_when_bq_fails() -> None:
    def boom(_syms: list[str]) -> list[object]:
        raise RuntimeError("bq down")

    assert batched_catalogue_fn(["NX.F.OPT.UFC-1"], query_fn=boom) is None


def test_batched_fn_lookup() -> None:
    row = _row("NX.F.OPT.UFC-1", "NX.F.OPT.UFC-1", "A vs B", datetime(2026, 8, 1, tzinfo=UTC))
    fn = batched_catalogue_fn(["NX.F.OPT.UFC-1"], query_fn=lambda syms: _select([row], syms))
    assert fn is not None
    assert fn("NX.F.OPT.UFC-1")["home_name"] == "A"
    assert fn("missing")["seen"] is False


def test_catalogue_sql_is_exact_symbols_only() -> None:
    from mappers.control_plane.gap_crypto_catalogue import _CATALOGUE_SQL

    assert "symbol in unnest(@syms)" in _CATALOGUE_SQL
    assert "@bases" not in _CATALOGUE_SQL


def _select(pool: list[SimpleNamespace], syms: list[str]) -> list[SimpleNamespace]:
    wanted = set(syms)
    return [row for row in pool if row.symbol in wanted]


def _row(symbol: str, base: str, name: str, published: datetime | None) -> SimpleNamespace:
    home, _sep, away = name.partition(" vs ")
    return SimpleNamespace(
        symbol=symbol,
        base=base,
        market_type="GAME",
        contract_type="MONEYLINE",
        meta_name=name,
        meta_event_date="",
        meta_league="UFC",
        home_id="1",
        away_id="2",
        home_name=home or name,
        away_name=away,
        publish_time=published,
    )
