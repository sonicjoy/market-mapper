"""SX Bet in gap-propose: inventory SQL key, classifier, planner seating, console Unmapped."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from mappers.control_plane import gap_fix_sxbet
from mappers.control_plane.console_platforms import explore_platform
from mappers.control_plane.console_unmapped import _CONSOLE_UNMAPPED_SQL, enrich_sxbet_rows, list_unmapped_legs
from mappers.control_plane.gap_fix import _sxbet_side
from mappers.control_plane.gap_fix_sxbet import (
    LEAGUE_NOT_WIRED,
    NEEDS_NAME_OR_OPTIC,
    NOT_IN_SX_CATALOGUE,
    TYPE_NOT_MAPPED,
    classify,
    fetch_sx_markets,
    harvest_sxbet_rfq,
    market_hash_of,
)
from mappers.control_plane.gap_inventory import RfqGapItem, rank_rfq_gaps
from mappers.control_plane.gap_inventory_league import LEAGUE_META_KEY, attach_league_tokens
from mappers.control_plane.gap_inventory_sql import RFQ_INVENTORY_SQL
from mappers.control_plane.pipeline_gap_batch import card_league
from mappers.control_plane.rfq_platforms import HARVEST_BOOKS, is_known_mapping_failure_platform
from mappers.exchanges.sxbet import selection_id

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sxbet" / "markets_active_2026-10-13.json"
RAW = json.loads(FIXTURE.read_text(encoding="utf-8"))


def _raw(o1: str, o2: str | None = None) -> dict[str, Any]:
    return next(r for r in RAW if r["outcomeOneName"] == o1 and (o2 is None or r["outcomeTwoName"] == o2))


SPREAD = _raw("SV Werder Bremen -1.5")                     # Bundesliga AH: league + type mapped
SOCCER_12 = _raw("SV Werder Bremen", "SC Paderborn 07")     # soccer type 52: not mapped
WOMENS_WC = {**SPREAD, "leagueId": 1516, "leagueLabel": "Women's World Cup"}


def _key(raw: dict[str, Any], outcome: int = 1) -> str:
    return selection_id(raw["marketHash"], outcome)


# === Registry / inventory ===

def test_sxbet_is_a_known_harvest_book() -> None:
    assert "sxbet" in HARVEST_BOOKS
    assert is_known_mapping_failure_platform("sxbet")
    ranked = rank_rfq_gaps([("sxbet", "0xa|two", 3)])
    assert [(i.book, i.key) for i in ranked] == [("sxbet", "0xa|two")]


def test_inventory_keys_sx_legs_on_the_maker_suffix() -> None:
    """The SQL flip must match sxbet.selection_id: a taker on outcome one reads |two."""
    sql = RFQ_INVENTORY_SQL
    assert "if(s.taker_outcome_one = 'true', 'two', 'one')" in sql
    assert selection_id("0xA", 1) == "0xa|two" and selection_id("0xa", 2) == "0xa|one"
    assert "sportsbook = 'SX Bet'" in sql
    assert "r.platform in ('sxbet')" in sql
    assert "PARTIAL_PRICING_TOO_FEW_SURVIVORS" in sql and "offer_sent_part_mapped" in sql
    assert "from sxbet_probe" in sql
    assert "__SXBET" not in sql


# === Classifier ===

@pytest.mark.parametrize(("raw", "reason"), [
    (SPREAD, NEEDS_NAME_OR_OPTIC),
    (SOCCER_12, TYPE_NOT_MAPPED),
    (WOMENS_WC, LEAGUE_NOT_WIRED),
    (None, NOT_IN_SX_CATALOGUE),
])
def test_classify(raw, reason) -> None:
    got, detail = classify(raw)
    assert got == reason
    if raw is not None:
        assert raw["teamOneName"] in detail and str(raw["type"]) in detail


def test_classify_names_the_slug_when_the_league_maps() -> None:
    assert classify(SPREAD)[1].startswith("germany_bundesliga: Soccer · German Bundesliga (244)")


def test_harvest_records_one_reason_per_key_and_no_pins() -> None:
    items = [RfqGapItem("sxbet", _key(SPREAD), 3), RfqGapItem("sxbet", _key(SOCCER_12, 2), 1),
             RfqGapItem("sxbet", "0xgone|one", 1), RfqGapItem("underdog", "UDX", 1)]
    skipped: list[dict[str, str]] = []
    walked: set[tuple[str, str]] = set()
    asked: list[list[str]] = []

    def fetch(hashes: list[str]) -> dict[str, dict[str, Any]]:
        asked.append(hashes)
        return {market_hash_of(_key(r)): r for r in (SPREAD, SOCCER_12)}

    harvest_sxbet_rfq(items, skipped, walked, fetch_fn=fetch)
    assert {s["key"]: s["reason"] for s in skipped} == {
        _key(SPREAD): NEEDS_NAME_OR_OPTIC, _key(SOCCER_12, 2): TYPE_NOT_MAPPED, "0xgone|one": NOT_IN_SX_CATALOGUE}
    assert walked == {("sxbet", k) for k in (_key(SPREAD), _key(SOCCER_12, 2), "0xgone|one")}
    assert len(asked) == 1 and "0xgone" in asked[0]


def test_an_sx_outage_walks_nothing_so_keys_retry() -> None:
    skipped: list[dict[str, str]] = []
    walked: set[tuple[str, str]] = set()

    def boom(_hashes: list[str]) -> dict[str, dict[str, Any]]:
        raise RuntimeError("sx down")

    harvest_sxbet_rfq([RfqGapItem("sxbet", "0xa|one", 1)], skipped, walked, fetch_fn=boom)
    assert walked == set()
    assert skipped == [{"book": "sxbet", "reason": "harvest_error:sx down"}]


def test_gap_fix_dispatch_returns_no_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gap_fix_sxbet, "fetch_sx_markets", lambda hashes: {})
    pins, skipped = _sxbet_side([RfqGapItem("sxbet", "0xa|one", 1)], None)
    assert pins == []
    assert skipped[0]["reason"] == NOT_IN_SX_CATALOGUE


class _Resp:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._body


class _Session:
    def __init__(self, body: dict[str, Any] | None = None) -> None:
        self.calls: list[str] = []
        self.body = body

    def get(self, url: str, params: dict[str, str], timeout: int) -> _Resp:
        self.calls.append(params["marketHashes"])
        hashes = params["marketHashes"].split(",")
        return _Resp(self.body or {"status": "success", "data": [{"marketHash": h.upper()} for h in hashes]})


def test_fetch_batches_at_thirty_and_lowercases() -> None:
    session = _Session()
    out = fetch_sx_markets([f"0x{i:02d}" for i in range(65)] + ["0x00"], session=session)
    assert [len(c.split(",")) for c in session.calls] == [30, 30, 5]
    assert len(out) == 65 and "0x00" in out


def test_fetch_raises_on_an_error_body() -> None:
    with pytest.raises(RuntimeError):
        fetch_sx_markets(["0x1"], session=_Session({"status": "failure"}))


# === Planner seating ===

def test_sx_keys_seat_on_their_tip_league_card() -> None:
    items = [RfqGapItem("sxbet", _key(SPREAD), 2), RfqGapItem("sxbet", "0xgone|one", 1)]

    def lookup(book: str, ids: list[str]) -> dict[str, dict[str, str]]:
        assert book == "sxbet"
        return {SPREAD["marketHash"].lower(): {"league": "germany_bundesliga"}} if ids else {}

    seated = attach_league_tokens(items, lookup_fn=lookup)
    assert (seated[0].meta or {})[LEAGUE_META_KEY] == "germany_bundesliga"
    assert card_league(seated[0], {}) == "germany_bundesliga"
    assert card_league(seated[1], {}) == "sxbet"


# === Console ===

def test_console_lists_sx_on_unmapped() -> None:
    row = explore_platform("sxbet")
    assert row is not None and row.sportsbook == "SX Bet" and row.unmapped_inventory
    assert not row.missing_catalogue
    assert "union all select * from sxbet" in _CONSOLE_UNMAPPED_SQL
    assert "if(s.taker_outcome_one = 'true', 'two', 'one')" in _CONSOLE_UNMAPPED_SQL


def test_console_titles_come_from_sxs_catalogue_and_survive_an_outage() -> None:
    rows = [{"platform": "sxbet", "key": _key(SPREAD, 2), "platform_leg_description": "0x", "fixture": "0x"},
            {"platform": "kalshi", "key": "K"}]
    out = enrich_sxbet_rows([dict(r) for r in rows], fetch_fn=lambda hs: {market_hash_of(_key(SPREAD)): SPREAD})
    assert out[0]["platform_leg_description"] == "SV Werder Bremen v SC Paderborn 07 — SC Paderborn 07 +1.5"
    assert out[0]["league"] == "German Bundesliga" and out[0]["sport"] == "soccer"
    assert out[0]["start_at"] == "2026-10-17T13:30:00Z"

    def boom(_hs: list[str]) -> dict[str, dict[str, Any]]:
        raise RuntimeError("down")

    assert enrich_sxbet_rows([dict(r) for r in rows], fetch_fn=boom) == rows


def test_list_unmapped_filters_to_sx() -> None:
    upcoming = {**SPREAD, "gameTime": int(time.time()) + 2 * 86400}  # pre-match whatever today is
    raw = [{"platform": "sxbet", "key": _key(SPREAD), "demand": 2, "last_seen": "2026-10-13T10:00:00Z",
            "platform_leg_description": "x", "fixture": "x", "start_at": None, "ttko_hours": None},
           {"platform": "kalshi", "key": "K", "demand": 9, "last_seen": "2026-10-13T10:00:00Z",
            "platform_leg_description": "k", "fixture": "k", "start_at": None, "ttko_hours": None}]
    page = list_unmapped_legs(platform="sxbet", phase="pre", query_fn=lambda p: [dict(r) for r in raw],
                              sx_fetch_fn=lambda hs: {market_hash_of(_key(SPREAD)): upcoming})
    assert [r["platform"] for r in page["rows"]] == ["sxbet"]
