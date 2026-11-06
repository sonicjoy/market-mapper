"""Polymarket US symbol lookup on the gateway (typed fields; never split)."""

from __future__ import annotations

from fetch import polymarket_usa_gateway as gw
from tests.conftest import us_gateway_market


def test_find_us_symbol_needs_the_gateway_to_know_it(us_gateway: dict[str, dict]) -> None:
    text = "do we map aec-atp-benbon-botzan-2026-08-27 ?"
    assert gw.find_us_symbol(text) == ""
    us_gateway["aec-atp-benbon-botzan-2026-08-27"] = us_gateway_market(
        "aec-atp-benbon-botzan-2026-08-27", league="atp",
        teams=(("benbon", "Benjamin Bonzi"), ("botzan", "Botic van de Zandschulp")),
    )
    assert gw.find_us_symbol(text) == "aec-atp-benbon-botzan-2026-08-27"


def test_summary_reads_typed_teams_and_league() -> None:
    row = gw.summary(us_gateway_market(
        "S", league="ufc", teams=(("ryagan", "Ryan Gandra"), ("ozzdia", "Ozzy Diaz")),
        smt="ufc_fight_winner", start="2026-09-19T23:00:00Z",
    ))
    assert row["slug"] == "s"
    assert row["league"] == "ufc"
    assert row["sports_market_type"] == "ufc_fight_winner"
    assert [t["abbreviation"] for t in row["teams"]] == ["ryagan", "ozzdia"]
    assert gw.summary(us_gateway_market("p"))["league"] == ""


def test_lookup_batches_caches_and_retries_failures() -> None:
    gw.clear_cache()
    calls: list[list[str]] = []

    def batch(symbols: list[str]) -> list[dict] | None:
        calls.append(symbols)
        if len(calls) == 1:
            return None  # gateway down: nothing cached
        return [us_gateway_market(s) for s in symbols if s.startswith("k")]

    syms = [f"k{i}" for i in range(150)] + ["x"]
    assert gw.lookup_markets(syms[:1], batch_fn=batch) == {}
    found = gw.lookup_markets(syms, batch_fn=batch)
    assert len(found) == 150
    assert [len(c) for c in calls[1:]] == [100, 51]
    gw.lookup_markets(syms, batch_fn=batch)
    assert len(calls) == 3  # hits and the miss are cached
    gw.clear_cache()
