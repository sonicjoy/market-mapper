"""Harvest + propose gap pins (injected Optic/crypto/Poly; no live BQ)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any


from mappers.control_plane.chat_intent import score_intent, wants_gap_fix
from mappers.control_plane.chat_router import handle_chat_turn
from mappers.control_plane.chat_session import session_bag
from mappers.control_plane.chat_tools import TOOL_SCHEMAS
from mappers.control_plane.gap_fix import (
    harvest_gap_pins,
    propose_gap_pins,
)
from mappers.control_plane.gap_fix_ai_suggest import AI_REF, is_ai_suggest_pin
from mappers.control_plane.gap_fix_keys import names_close
from mappers.control_plane.gap_fix_poly import harvest_poly_side
from mappers.control_plane.gap_fix_slots import PinSlots
from mappers.control_plane.gap_fix_verify import (
    drop_clone_on_existing,
    verify_submit,
)
from mappers.control_plane.gap_fix_verify import (
    drop_implicated as _drop_implicated,
)
from mappers.control_plane.gap_inventory import MAX_EVENTS, RfqGapItem, rank_rfq_gaps
from mappers.control_plane.live_evidence import EvidenceHit, probe_pin_evidence
from mappers.control_plane.models import Actor, ActorRole, BatchChangesPayload, ChatRequest
from mappers.control_plane.pin_flow import verify_pins
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.settings import Settings
from tests.control_plane.gap_store_helpers import (
    _fixtures,
    _league,
    _soccer_store,
    _store,
)


def _admin() -> Actor:
    return Actor(subject="admin@wsd.com", role=ActorRole.ADMIN)


def _poly_us_league(
    slug: str, optic: str, us_code: str, *, enabled: bool = True,
    sport: str = "soccer",
) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport=sport,
        optic_league_id=optic,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "polymarket_usa",
                "enabled": enabled,
                "parser_profile": "poly_usa_generic_v1",
                "source_league_id": us_code,
                "settings": {"slug_prefix": us_code},
            }
        ],
    )


def _us_event(
    inner: str,
    home: str,
    away: str,
    day: str = "2026-08-29",
    *,
    title: str = "",
    team_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "inner": inner,
        "home": home,
        "away": away,
        "date": day,
        "ticker": f"pm-{inner}-{home}-{away}-{day}",
    }
    if title:
        row["title"] = title
    if team_names:
        row["team_names"] = team_names
    return row


def _optic_row(
    optic_id: str,
    home_abbr: str,
    home_name: str,
    home_id: str,
    away_abbr: str,
    away_name: str,
    away_id: str,
    day: str = "2026-08-29",
) -> dict[str, Any]:
    return {
        "optic_league_id": optic_id,
        "d": day,
        "home_abbr": home_abbr,
        "home_name": home_name,
        "home_id": home_id,
        "away_abbr": away_abbr,
        "away_name": away_name,
        "away_id": away_id,
        "sport": "soccer",
    }


def test_schema_omits_harvest_gap_pins() -> None:
    names = {row["name"] for row in TOOL_SCHEMAS}
    assert "harvest_gap_pins" not in names


def test_fix_gaps_intent() -> None:
    assert wants_gap_fix("fix gaps")
    assert wants_gap_fix("harvest the gaps")
    assert not wants_gap_fix("how many gaps")
    scored = score_intent("fix gaps", tip_leagues={"la_liga"})
    assert scored.intent == "entity_alias"
    assert scored.confidence >= 0.9
    session_bag().clear()
    reply = handle_chat_turn(
        ChatRequest(message="fix gaps", conversation_id="c1"),
        settings=Settings(
            gcp_project="marketmaking-test",
            chat_enabled=True,
            chat_provider="fake",
            chat_model="fake",
        ),
        store=_soccer_store(),
    )
    assert "Proposed" in reply.reply_markdown
    assert reply.ui_actions == [{"type": "navigate", "path": "/review"}]


def test_rank_rfq_keeps_a_full_cap_per_book() -> None:
    rows = [("polymarket", f"slug{i}", 100 - i) for i in range(40)]
    rows += [("crypto", f"NX.F.OPT.FIFA-{i}", 50 - i) for i in range(30)]
    rows += [("kalshi", f"KX{i}", 999) for i in range(5)]
    ranked = rank_rfq_gaps(rows, limit=MAX_EVENTS)
    poly = [item for item in ranked if item.book == "polymarket"]
    crypto = [item for item in ranked if item.book == "crypto"]
    assert len(poly) == 40
    assert len(crypto) == 30
    assert poly[0].demand >= poly[-1].demand
    assert not [item for item in ranked if item.book == "kalshi"]


def test_harvest_logs_inventory_and_probe_stages(caplog: Any) -> None:
    with caplog.at_level(logging.INFO, logger="mappers.control_plane.gap_fix"):
        harvest_gap_pins(
            _soccer_store(),
            symbols=["NX.F.OPT.FIFA-00001-260901-M.O.1.1"],
            fixtures_fn=_fixtures,
            catalogue_fn=lambda _s: {"ok": True, "seen": False, "symbol": _s},
        )
    assert "stage=inventory" in caplog.text
    assert "stage=probe book=crypto" in caplog.text


def test_harvest_warms_optic_cache_when_fixtures_not_injected(monkeypatch: Any) -> None:
    called: list[tuple[object, object]] = []
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix.warm_optic_cache",
        lambda store, leagues=None: called.append((store, leagues)),
    )
    harvest_gap_pins(
        _soccer_store(),
        poly_prefixes=["efl"],
        us_events_fn=list,
        official_events_fn=list,
        optic_rows_fn=list,
    )
    assert called
    assert called[0][1] is None


def test_harvest_optic_missing_when_rfq_drafted(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix.harvest_missing_optic_competitors",
        lambda *_a, **_k: calls.append("missing"),
    )
    harvest_gap_pins(
        _soccer_store(),
        symbols=["NX.F.OPT.FIFA-00001-260901-M.O.1.1"],
        fixtures_fn=_fixtures,
        catalogue_fn=lambda _s: {"ok": True, "seen": False, "symbol": _s},
    )
    assert calls == ["missing"]


def test_harvest_optic_missing_when_rfq_empty(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix.harvest_missing_optic_competitors",
        lambda *_a, **_k: calls.append("missing"),
    )
    harvest_gap_pins(
        _soccer_store(),
        symbols=[],
        poly_prefixes=[],
        fixtures_fn=_fixtures,
    )
    assert calls == ["missing"]


def test_harvest_crypto_missing_when_rfq_empty(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "mappers.control_plane.gap_fix.harvest_missing_crypto_ids",
        lambda *_a, **_k: calls.append("missing"),
    )
    harvest_gap_pins(
        _soccer_store(),
        symbols=[],
        poly_prefixes=[],
        fixtures_fn=_fixtures,
    )
    assert calls == ["missing"]


def test_harvest_batches_crypto_catalogue(monkeypatch: Any) -> None:
    seen: list[str] = []

    def fake(symbols: list[str], **_k: Any) -> Any:
        seen.extend(symbols)
        return lambda s: {"ok": True, "seen": False, "symbol": s}

    monkeypatch.setattr("mappers.control_plane.gap_fix.batched_catalogue_fn", fake)
    harvest_gap_pins(
        _soccer_store(),
        symbols=["NX.F.OPT.FIFA-00001-260901-M.O.1.1"],
        fixtures_fn=_fixtures,
    )
    assert seen == ["NX.F.OPT.FIFA-00001-260901-M.O.1.1"]


def test_harvest_uses_separate_pin_slots_per_book(monkeypatch: Any) -> None:
    made: list[PinSlots] = []

    class _Track(PinSlots):
        def __init__(self, limit: int = MAX_EVENTS) -> None:
            made.append(self)
            super().__init__(limit=limit)

    def _slots(*, drain: bool) -> PinSlots:
        return _Track(limit=MAX_EVENTS)

    monkeypatch.setattr("mappers.control_plane.gap_fix.pin_slots_for_drain", _slots)
    harvest_gap_pins(
        _soccer_store(),
        symbols=["NX.F.OPT.FIFA-00001-260901-M.O.1.1"],
        poly_prefixes=["efl"],
        fixtures_fn=_fixtures,
        catalogue_fn=lambda _s: {"ok": True, "seen": False},
        us_events_fn=list,
        official_events_fn=list,
        optic_rows_fn=list,
    )
    assert len(made) == 2


def test_verify_strips_already_live_book_code_from_pin() -> None:
    val = EntityRow(
        league="la_liga",
        entity_type="team",
        canonical_key="VAL",
        canonical_name="Valencia",
        aliases=[
            {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "vcf"},
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "oid-val"},
        ],
    )
    store = _store([val], [_league("la_liga", "spain_-_la_liga")])
    pin = {
        "kind": "entity_alias",
        "league": "la_liga",
        "canonical_key": "VAL",
        "canonical_name": "Valencia",
        "entity_type": "team",
        "aliases": [
            {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "vcf"},
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "oid-new"},
        ],
        "evidence_refs": ["gap:usa-inner:lal"],
        "reassign": False,
    }
    kept, _skipped = verify_pins(store, [pin], probe=None)
    assert len(kept) == 1
    values = [a["alias_value"] for a in kept[0]["aliases"]]
    assert values == ["oid-new"]


def _crypto_alias_pin(key: str, name: str, cid: str) -> dict[str, Any]:
    return {
        "kind": "entity_alias",
        "league": "la_liga",
        "canonical_key": key,
        "entity_type": "team",
        "canonical_name": name,
        "aliases": [
            {"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": cid},
        ],
        "reassign": False,
    }


def test_propose_skips_name_mismatch_keeps_other() -> None:
    def probe(_store: Any, *, alias_value: str, **_k: Any) -> EvidenceHit:
        if alias_value == "90000933":
            return EvidenceHit(
                blocker=(
                    "crypto.com 90000933 is live as 'Sao Paulo FC', "
                    "not 'Santos FC Sao Paulo'."
                ),
            )
        return EvidenceHit(refs=(f"crypto_id:{alias_value}",))

    svc = ProposalService(_soccer_store(), evidence_fn=probe)
    result = propose_gap_pins(
        svc,
        _admin(),
        [
            _crypto_alias_pin("BET", "Santos FC Sao Paulo", "90000933"),
            _crypto_alias_pin("VAL", "Valencia", "ok-id"),
        ],
        acknowledge_shadow=True,
    )
    assert result["ok"] is True
    assert result["count"] == 1
    assert any("90000933" in item for item in result["skipped_blockers"])
    prop = svc.get_proposal(result["review"]["ref"])
    payload = prop.payload
    assert isinstance(payload, BatchChangesPayload)
    assert payload.entity_aliases[0].canonical_key == "VAL"


def test_propose_keeps_ai_suggestion_when_live_name_mismatches() -> None:
    """AI pins skip names_fit; unique-bind already failed that check."""

    def probe(_store: Any, **_k: Any) -> EvidenceHit:
        return EvidenceHit(
            blocker=(
                "crypto.com 90000933 is live as 'Sao Paulo FC', "
                "not 'Valencia'."
            ),
        )

    svc = ProposalService(_soccer_store(), evidence_fn=probe)
    pin = _crypto_alias_pin("VAL", "Valencia", "90000933")
    pin["evidence_refs"] = [AI_REF]
    result = propose_gap_pins(svc, _admin(), [pin], acknowledge_shadow=True)
    assert result["ok"] is True
    payload = svc.get_proposal(result["review"]["ref"]).payload
    assert isinstance(payload, BatchChangesPayload)
    assert is_ai_suggest_pin(payload.entity_aliases[0])
    assert payload.entity_aliases[0].canonical_key == "VAL"


def test_propose_live_evidence_once_per_pin() -> None:
    """Harvest Review live-checks every alias once (not per-pin then batch)."""
    calls: list[str] = []

    def probe(_store: Any, *, alias_value: str, **_k: Any) -> EvidenceHit:
        calls.append(alias_value)
        return EvidenceHit(refs=(f"crypto_id:{alias_value}",))

    svc = ProposalService(_soccer_store(), evidence_fn=probe)
    result = propose_gap_pins(
        svc,
        _admin(),
        [
            _crypto_alias_pin("VAL", "Valencia", "id-1"),
            _crypto_alias_pin("BET", "Real Betis", "id-2"),
            _crypto_alias_pin("SEV", "Sevilla", "id-3"),
        ],
        acknowledge_shadow=True,
    )
    assert result["ok"] is True
    assert result["count"] == 3
    assert calls == ["id-1", "id-2", "id-3"]


def test_shared_probe_is_probe_pin_evidence() -> None:
    """CronJob harvest verify and console entry_batch_verify share probe_pin_evidence."""
    svc = ProposalService(_soccer_store(), evidence_fn=probe_pin_evidence)
    assert svc.evidence_fn is probe_pin_evidence


def test_inventory_fn_rfq_items() -> None:
    items = [
        RfqGapItem("crypto", "NX.F.OPT.LALIGA-1", 9),
        RfqGapItem("crypto", "NX.F.OPT.LALIGA-2", 3),
    ]
    result = harvest_gap_pins(
        _soccer_store(),
        inventory_fn=lambda: items,
        fixtures_fn=_fixtures,
        catalogue_fn=lambda _s: {"ok": True, "seen": False, "symbol": _s},
    )
    assert result["inventory"][0]["key"] == "NX.F.OPT.LALIGA-1"


def test_harvest_poly_skips_after_no_us_events() -> None:
    result = harvest_gap_pins(
        _soccer_store(),
        poly_prefixes=["efl", "kor"],
        us_events_fn=list,
        official_events_fn=list,
        optic_rows_fn=list,
    )
    assert result["pins"] == []
    by_key = {row["key"]: row["reason"] for row in result["skipped"] if row.get("book") == "polymarket"}
    assert by_key["efl"] == "missing_us_events"
    assert by_key["kor"] == "missing_us_events"
    assert any(row["book"] == "polymarket" and row["key"] == "efl" for row in result["inventory"])


def test_harvest_poly_wired_without_us_events_skips() -> None:
    store = _store([], [_poly_us_league("korea_k1", "korea_-_k_league_1", "kor")])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["kor", "efl"],
        us_events_fn=list,
        official_events_fn=list,
        optic_rows_fn=list,
    )
    by_key = {row["key"]: row["reason"] for row in result["skipped"] if row.get("book") == "polymarket"}
    assert by_key["kor"] == "missing_us_events"
    assert by_key["efl"] == "missing_us_events"


def test_harvest_poly_wired_drafts_usa_aliases() -> None:
    store = _store([], [_poly_us_league("korea_k1", "korea_-_k_league_1", "kor")])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["kor"],
        us_events_fn=lambda: [_us_event(
            "kor", "seo", "uls",
            title="FC Seoul vs. Ulsan Hyundai",
            team_names={"seo": "FC Seoul", "uls": "Ulsan Hyundai"},
        )],
        official_events_fn=list,
        optic_rows_fn=lambda: [
            _optic_row(
                "korea_-_k_league_1", "SUFC", "FC Seoul", "oid-seo",
                "UHD", "Ulsan Hyundai", "oid-uls",
            )
        ],
    )
    assert result["skipped"] == []
    values = {a["alias_value"] for p in result["pins"] for a in p["aliases"]}
    assert "seo" in values
    assert "uls" in values
    assert "oid-seo" in values
    books = {a["sportsbook"] for p in result["pins"] for a in p["aliases"]}
    assert "polymarket_usa" in books
    assert "optic" in books
    refs = [r for p in result["pins"] for r in p["evidence_refs"]]
    assert "polymarket_usa:name:FC Seoul" in refs
    assert "polymarket_usa:name:Ulsan Hyundai" in refs
    assert "polymarket_usa:title:FC Seoul vs. Ulsan Hyundai" in refs
    assert any(r.startswith("polymarket_usa:ticker:") for r in refs)
    assert any(r.startswith("polymarket_usa:match:") for r in refs)
    assert any(r.startswith("optic:fixture:") and "FC Seoul vs Ulsan Hyundai" in r for r in refs)
    assert {p["entity_type"] for p in result["pins"]} == {"team"}


def test_harvest_poly_us_mints_ufc_as_fighter() -> None:
    """Poly US with no Optic owner must mint the league match-side type."""
    store = _store([], [_poly_us_league("ufc", "ufc", "ufc", sport="mma")])
    pins, skipped = harvest_poly_side(
        store,
        ["ufc"],
        [_us_event(
            "ufc", "jonj", "alexp",
            title="Jon Jones vs. Alex Pereira",
            team_names={"jonj": "Jon Jones", "alexp": "Alex Pereira"},
        )],
        [_optic_row(
            "ufc", "JONES", "Jon Jones", "oid-jones",
            "PEREI", "Alex Pereira", "oid-pereira",
        )],
    )
    assert skipped == []
    assert pins
    assert {p["entity_type"] for p in pins} == {"fighter"}


def test_harvest_poly_side_coalesces_entities_once() -> None:
    """Poly US draft indexes the tip once, not per event side."""
    store = _store([], [_poly_us_league("ufc", "ufc", "ufc", sport="mma")])
    calls = {"n": 0}
    orig = store.entities_for

    def wrapped(rid: str) -> Any:
        calls["n"] += 1
        return orig(rid)

    store.entities_for = wrapped  # type: ignore[method-assign]
    harvest_poly_side(
        store,
        ["ufc"],
        [_us_event(
            "ufc", "jonj", "alexp",
            title="Jon Jones vs. Alex Pereira",
            team_names={"jonj": "Jon Jones", "alexp": "Alex Pereira"},
        )],
        [_optic_row(
            "ufc", "JONES", "Jon Jones", "oid-jones",
            "PEREI", "Alex Pereira", "oid-pereira",
        )],
        persist_ttl=False,
    )
    assert calls["n"] == 1


def test_harvest_poly_stops_when_pin_slots_full() -> None:
    store = _store([], [_poly_us_league("korea_k1", "korea_-_k_league_1", "kor")])
    events = [
        _us_event("kor", "seo", "uls", title="FC Seoul vs. Ulsan Hyundai",
                  team_names={"seo": "FC Seoul", "uls": "Ulsan Hyundai"}),
        _us_event("k2", "a", "b", title="A vs B", team_names={"a": "A", "b": "B"}),
    ]
    rows = [
        _optic_row("korea_-_k_league_1", "SUFC", "FC Seoul", "oid-seo", "UHD", "Ulsan Hyundai", "oid-uls"),
        _optic_row("korea_-_k_league_2", "A", "A", "oid-a", "B", "B", "oid-b"),
    ]
    pins, _skipped = harvest_poly_side(
        store, ["kor", "k2"], events, rows, slots=PinSlots(limit=1),
    )
    tickers = {
        str(r).split(":")[-1]
        for p in pins
        for r in p.get("evidence_refs") or []
        if str(r).startswith("polymarket_usa:ticker:")
    }
    assert pins
    assert any("kor" in t for t in tickers)
    assert all("k2" not in t for t in tickers)


def test_harvest_poly_wired_pins_when_codes_miss_but_optic_names_match() -> None:
    """Sweeper must propose USA aliases when Optic names uniquely match."""
    store = _store([], [_poly_us_league("itf_men", "itf_men", "itf")])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["itf"],
        us_events_fn=lambda: [_us_event(
            "itf", "jsinxx", "calcar",
            title="Jannik Sinner vs. Carlos Alcaraz",
            team_names={"jsinxx": "Jannik Sinner", "calcar": "Carlos Alcaraz"},
        )],
        official_events_fn=list,
        optic_rows_fn=lambda: [
            _optic_row(
                "itf_men", "", "Jannik Sinner", "oid-sin",
                "", "Carlos Alcaraz", "oid-alc",
            )
        ],
    )
    assert result["skipped"] == []
    values = {a["alias_value"] for p in result["pins"] for a in p["aliases"]}
    assert "jsinxx" in values
    assert "calcar" in values
    assert "oid-sin" in values
    refs = [r for p in result["pins"] for r in p["evidence_refs"]]
    assert "polymarket_usa:name:Jannik Sinner" in refs
    assert "optic:competitor:oid-sin:Jannik Sinner" in refs


def test_harvest_poly_enables_us_on_existing_league() -> None:
    store = _soccer_store()
    result = harvest_gap_pins(
        store,
        poly_prefixes=["lal"],
        us_events_fn=lambda: [_us_event("lal", "val", "bet")],
        official_events_fn=list,
        optic_rows_fn=lambda: [
            _optic_row(
                "spain_-_la_liga", "VCFC", "Valencia CF", "oid-val",
                "RBB", "Real Betis", "oid-bet",
            )
        ],
    )
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert len(leagues) == 1
    assert leagues[0]["league"] == "la_liga"
    usa = next(ex for ex in leagues[0]["exchanges"] if ex["sportsbook"] == "polymarket_usa")
    assert usa["enabled"] is True
    assert usa["source_league_id"] == "lal"
    aliases = [p for p in result["pins"] if p.get("kind") == "entity_alias"]
    assert aliases


def test_harvest_poly_enables_disabled_us_pin() -> None:
    store = _store(
        [],
        [_poly_us_league("italy_coppa_italia", "italy_-_coppa_italia", "cop", enabled=False)],
    )
    result = harvest_gap_pins(
        store,
        poly_prefixes=["cop"],
        us_events_fn=lambda: [_us_event("cop", "udi", "ven")],
        official_events_fn=list,
        optic_rows_fn=lambda: [
            _optic_row(
                "italy_-_coppa_italia", "UDI", "Udinese", "oid-udi",
                "VEN", "Venezia", "oid-ven",
            )
        ],
    )
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert len(leagues) == 1
    usa = next(ex for ex in leagues[0]["exchanges"] if ex["sportsbook"] == "polymarket_usa")
    assert usa["enabled"] is True
    assert usa["source_league_id"] == "cop"


def test_harvest_poly_onboards_unique_optic_league() -> None:
    store = _soccer_store()
    result = harvest_gap_pins(
        store,
        poly_prefixes=["par2"],
        us_events_fn=lambda: [_us_event("par2", "cer", "gua")],
        official_events_fn=list,
        optic_rows_fn=lambda: [
            _optic_row(
                "paraguay_-_division_intermedia", "CERC", "Cerro Porteno", "oid-cer",
                "GUAR", "Guarani Asuncion", "oid-gua",
            )
        ],
    )
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert len(leagues) == 1
    assert leagues[0]["league"] == "paraguay_division_intermedia"
    assert leagues[0]["clone_market_rules_from"] == "la_liga"
    usa = next(ex for ex in leagues[0]["exchanges"] if ex["sportsbook"] == "polymarket_usa")
    assert usa["enabled"] is True
    assert usa["source_league_id"] == "par2"
    assert all(p.get("kind") != "entity_alias" for p in result["pins"])


def test_harvest_poly_unwired_requires_majority_optic() -> None:
    store = _soccer_store()
    result = harvest_gap_pins(
        store,
        poly_prefixes=["xyz"],
        us_events_fn=lambda: [
            _us_event("xyz", "aaa", "bbb"),
            _us_event("xyz", "ccc", "ddd"),
            _us_event("xyz", "seo", "uls"),
        ],
        official_events_fn=list,
        optic_rows_fn=lambda: [
            _optic_row(
                "korea_-_k_league_1", "SUFC", "FC Seoul", "oid-seo",
                "UHD", "Ulsan Hyundai", "oid-uls",
            )
        ],
    )
    assert result["pins"] == []
    by_key = {row["key"]: row["reason"] for row in result["skipped"] if row.get("book") == "polymarket"}
    assert by_key["xyz"] == "missing_optic"


def test_harvest_poly_missing_optic_after_try() -> None:
    result = harvest_gap_pins(
        _soccer_store(),
        poly_prefixes=["setkameua"],
        us_events_fn=lambda: [_us_event("setkameua", "aaa", "bbb")],
        official_events_fn=list,
        optic_rows_fn=lambda: [
            _optic_row(
                "spain_-_la_liga", "VCFC", "Valencia CF", "oid-val",
                "RBB", "Real Betis", "oid-bet",
            )
        ],
    )
    assert result["pins"] == []
    by_key = {row["key"]: row["reason"] for row in result["skipped"] if row.get("book") == "polymarket"}
    assert by_key["setkameua"] == "no_optic_book"


def test_harvest_poly_disables_wired_non_optic_inner() -> None:
    store = _store([], [_poly_us_league(
        "norway_3_division", "norway_-_3_division", "setkameua",
    )])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["setkameua"],
        us_events_fn=lambda: [_us_event("setkameua", "makyar", "varole")],
        official_events_fn=list,
        optic_rows_fn=list,
    )
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert len(leagues) == 1
    assert leagues[0]["league"] == "norway_3_division"
    usa = next(ex for ex in leagues[0]["exchanges"] if ex["sportsbook"] == "polymarket_usa")
    assert usa["enabled"] is False
    by_key = {row["key"]: row["reason"] for row in result["skipped"] if row.get("book") == "polymarket"}
    assert by_key["setkameua"] == "no_optic_book"


def test_propose_poly_league_pin_creates_review() -> None:
    store = _soccer_store()
    harvested = harvest_gap_pins(
        store,
        poly_prefixes=["par2"],
        us_events_fn=lambda: [_us_event("par2", "cer", "gua")],
        official_events_fn=list,
        optic_rows_fn=lambda: [
            _optic_row(
                "paraguay_-_division_intermedia", "CERC", "Cerro Porteno", "oid-cer",
                "GUAR", "Guarani Asuncion", "oid-gua",
            )
        ],
    )
    svc = ProposalService(store)
    created = propose_gap_pins(
        svc,
        _admin(),
        harvested["pins"],
        acknowledge_shadow=True,
    )
    assert created["ok"] is True
    assert created["review"]["artifact"] == "batch_changes"
    prop = svc.get_proposal(created["review"]["ref"])
    payload = prop.payload
    assert isinstance(payload, BatchChangesPayload)
    assert payload.leagues[0].league == "paraguay_division_intermedia"


def test_names_close_helpers() -> None:
    assert names_close("Valencia", "Valencia CF", player=False)


def test_crypto_harvest_name_aligns_flipped_optic_home() -> None:
    """Catalogue home/away can disagree with Optic; pin by name, not index."""
    song_cid, umar_cid = "140000440", "140000905"
    song_oid, umar_oid = "oid-song", "oid-umar"
    kickoff = datetime.now(UTC) + timedelta(hours=24)
    cat_kickoff = kickoff.isoformat()
    optic_kickoff = kickoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    store = _store(
        [
            EntityRow(
                league="ufc",
                entity_type="fighter",
                canonical_key="SYO",
                canonical_name="Song Yadong",
                aliases=[
                    {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": song_oid},
                ],
            ),
            EntityRow(
                league="ufc",
                entity_type="fighter",
                canonical_key="NUR",
                canonical_name="Umar Nurmagomedov",
                aliases=[
                    {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": umar_oid},
                ],
            ),
        ],
        [
            LeagueRow(
                league="ufc",
                sport="mma",
                optic_league_id="ufc",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=168.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "crypto.com",
                        "enabled": True,
                        "parser_profile": "crypto_generic_v1",
                        "source_league_id": "UFC",
                        "settings": {"league": "UFC", "sport_grouping": "MMA"},
                    }
                ],
            )
        ],
    )

    def catalogue(_symbol: str) -> dict[str, Any]:
        return {
            "ok": True,
            "seen": True,
            "symbol": _symbol,
            "meta_name": "Umar Nurmagomedov vs Song Yadong",
            "meta_league": "UFC",
            "meta_event_date": cat_kickoff,
            "contract_type": "Moneyline",
            "home_id": song_cid,
            "away_id": umar_cid,
            "home_name": "Song Yadong",
            "away_name": "Umar Nurmagomedov",
        }

    def fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": "fx-umar-song",
                "start_date": optic_kickoff,
                "home_competitors": [{"id": umar_oid, "name": "Umar Nurmagomedov"}],
                "away_competitors": [{"id": song_oid, "name": "Song Yadong"}],
            }
        ]

    result = harvest_gap_pins(
        store,
        symbols=["NX.F.OPT.UFC-00001-260829-M.O.1.1.20261230"],
        catalogue_fn=catalogue,
        fixtures_fn=fixtures,
    )
    by_cid = {
        a["alias_value"]: p["canonical_key"]
        for p in result["pins"]
        for a in p["aliases"]
        if a.get("sportsbook") == "crypto.com"
    }
    assert by_cid[song_cid] == "SYO"
    assert by_cid[umar_cid] == "NUR"


def test_drop_implicated_uses_token_boundaries() -> None:
    pins = [
        {
            "league": "epl",
            "aliases": [
                {"sportsbook": "px", "alias_kind": "code", "alias_value": "UNI"},
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "uni"},
            ],
        },
        {
            "league": "epl",
            "aliases": [
                {"sportsbook": "px", "alias_kind": "code", "alias_value": "VCF"},
            ],
        },
    ]
    kept, dropped = _drop_implicated(
        pins,
        [
            "community shield residual",
            "px code VCF rejected for epl.",
        ],
    )
    assert len(kept) == 1
    assert kept[0]["aliases"] == pins[0]["aliases"]
    assert any("VCF" in item for item in dropped)


def test_drop_implicated_strips_optic_keeps_book_on_inactive_miss() -> None:
    pins = [
        {
            "aliases": [
                {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "DEAD1"},
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "ryagan"},
            ],
        },
        {
            "aliases": [
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "joabri"},
            ],
        },
    ]
    kept, _dropped = _drop_implicated(
        pins,
        ["Optic competitor DEAD1 not in active ufc fixtures."],
    )
    assert len(kept) == 2
    mixed = next(
        pin for pin in kept
        if any(a.get("alias_value") == "ryagan" for a in pin["aliases"])
    )
    assert mixed["aliases"] == [
        {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "ryagan"},
    ]
    assert kept[1]["aliases"][0]["alias_value"] == "joabri"


def test_drop_implicated_strips_optic_keeps_crypto_on_inactive_miss() -> None:
    pins = [{
        "aliases": [
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "DC99"},
            {"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "88001"},
        ],
    }]
    kept, _dropped = _drop_implicated(
        pins,
        ["Optic competitor DC99 not in active atp fixtures."],
    )
    assert len(kept) == 1
    assert kept[0]["aliases"] == [
        {"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "88001"},
    ]


def test_drop_implicated_rewrites_optic_name_with_apostrophe() -> None:
    pins = [{
        "canonical_name": "Nice",
        "aliases": [
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OID1"},
        ],
    }]
    live = "OGC Nice Côte d'Azur"
    kept, _dropped = _drop_implicated(
        pins,
        [f"Optic OID1 is {live!r}, not 'Nice'."],
    )
    assert kept[0]["canonical_name"] == live
    pins = [{
        "canonical_name": "Right Name",
        "aliases": [
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OID1"},
            {"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "88001"},
        ],
    }]
    kept, _dropped = _drop_implicated(
        pins,
        ["Optic OID1 is 'Wrong Name', not 'Right Name'."],
    )
    assert len(kept) == 1
    assert kept[0]["canonical_name"] == "Wrong Name"
    assert kept[0]["aliases"] == pins[0]["aliases"]


def test_drop_implicated_strips_optic_on_league_miss() -> None:
    pins = [
        {
            "league": "uwcl",
            "aliases": [
                {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OID1"},
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "chewom"},
            ],
        },
        {
            "league": "nhl",
            "aliases": [
                {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OID2"},
            ],
        },
    ]
    kept, _dropped = _drop_implicated(
        pins,
        ["No Optic league id on tip for uwcl."],
    )
    assert [pin["league"] for pin in kept] == ["uwcl", "nhl"]
    assert kept[0]["aliases"] == [
        {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "chewom"},
    ]
    assert kept[1]["aliases"][0]["alias_value"] == "OID2"


def test_drop_implicated_strips_optic_on_fixture_lookup_failed() -> None:
    pins = [
        {
            "league": "ufc",
            "aliases": [
                {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OID1"},
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "ryagan"},
            ],
        },
        {
            "league": "nhl",
            "aliases": [
                {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OID2"},
            ],
        },
    ]
    kept, _dropped = _drop_implicated(
        pins,
        ["Optic fixture lookup failed for ufc: key-miss: timeout"],
    )
    assert [pin["league"] for pin in kept] == ["ufc", "nhl"]
    assert kept[0]["aliases"] == [
        {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "ryagan"},
    ]
    assert kept[1]["aliases"][0]["alias_value"] == "OID2"


def test_drop_implicated_strips_crypto_on_catalogue_lookup_failed() -> None:
    pins = [
        {
            "league": "ufc",
            "aliases": [
                {"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "88001"},
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "ryagan"},
            ],
        },
        {
            "league": "nhl",
            "aliases": [
                {"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "99"},
            ],
        },
    ]
    kept, _dropped = _drop_implicated(
        pins,
        ["crypto.com catalogue lookup failed for ufc: 503"],
    )
    assert [pin["league"] for pin in kept] == ["ufc", "nhl"]
    assert kept[0]["aliases"][0]["sportsbook"] == "polymarket_usa"
    assert kept[1]["aliases"][0]["alias_value"] == "99"


def test_drop_implicated_inactive_miss_keeps_sibling_league_pin() -> None:
    pins = [
        {
            "league": "ufc",
            "canonical_key": "RYA",
            "aliases": [
                {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "DEAD1"},
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "ryagan"},
            ],
        },
        {
            "league": "ufc",
            "canonical_key": "VAL",
            "aliases": [{"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "ok-id"}],
        },
    ]
    kept, _dropped = _drop_implicated(
        pins,
        ["Optic competitor DEAD1 not in active ufc fixtures."],
    )
    assert [pin["canonical_key"] for pin in kept] == ["RYA", "VAL"]
    books = {alias["sportsbook"] for alias in kept[0]["aliases"]}
    assert books == {"polymarket_usa"}


def test_verify_submit_retries_after_optic_name_rewrite() -> None:

    class _Svc:
        store = None

        def __init__(self) -> None:
            self.bodies: list[Any] = []

        def entry_batch_verify(self, body: Any) -> dict[str, Any]:
            self.bodies.append(body)
            name = body.entity_aliases[0].canonical_name
            if name != "Ryan Garcia":
                return {
                    "ok": False,
                    "blockers": ["Optic DEAD1 is 'Ryan Garcia', not 'Garcia'."],
                }
            return {"ok": True, "preview_token": "tok", "warnings": []}

        def entry_batch_submit(self, token: str, actor: Any) -> dict[str, str]:
            return {"ref": "prop_name"}

    pins = [{
        "league": "ufc",
        "canonical_key": "RYA",
        "canonical_name": "Garcia",
        "aliases": [
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "DEAD1"},
            {"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "88001"},
        ],
    }]
    svc = _Svc()
    result = verify_submit(svc, _admin(), pins, [], True, "note")
    assert result["ok"] is True
    assert result["review"]["ref"] == "prop_name"
    assert svc.bodies[0].entity_aliases[0].canonical_name == "Garcia"
    assert svc.bodies[1].entity_aliases[0].canonical_name == "Ryan Garcia"
    books = {pin.sportsbook for pin in svc.bodies[1].entity_aliases[0].aliases}
    assert books == {"optic", "crypto.com"}


def test_verify_submit_retries_after_optic_strip() -> None:

    class _Svc:
        store = None

        def __init__(self) -> None:
            self.bodies: list[Any] = []

        def entry_batch_verify(self, body: Any) -> dict[str, Any]:
            self.bodies.append(body)
            if len(self.bodies) == 1:
                return {
                    "ok": False,
                    "blockers": ["Optic competitor DEAD1 not in active ufc fixtures."],
                }
            return {"ok": True, "preview_token": "tok", "warnings": []}

        def entry_batch_submit(self, token: str, actor: Any) -> dict[str, str]:
            return {"ref": "prop_retry"}

    svc = _Svc()
    pins = [{
        "league": "ufc",
        "canonical_key": "RYA",
        "canonical_name": "Ryan Garcia",
        "aliases": [
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "DEAD1"},
            {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "ryagan"},
        ],
    }]
    result = verify_submit(svc, _admin(), pins, [], True, "note")
    assert result["ok"] is True
    assert len(svc.bodies) == 2
    second = svc.bodies[1].entity_aliases[0]
    books = {pin.sportsbook for pin in second.aliases}
    assert books == {"polymarket_usa"}


def test_verify_submit_blocked_when_all_pins_dropped() -> None:

    class _Svc:
        store = None

        def __init__(self) -> None:
            self.calls = 0

        def entry_batch_verify(self, body: Any) -> dict[str, Any]:
            self.calls += 1
            return {
                "ok": False,
                "blockers": ["px code BAD not seen on open markets for epl."],
            }

    pins = [{
        "league": "epl",
        "canonical_key": "BAD",
        "aliases": [{"sportsbook": "px", "alias_kind": "code", "alias_value": "BAD"}],
    }]
    svc = _Svc()
    result = verify_submit(svc, _admin(), pins, [], True, "note")
    assert result["ok"] is False
    assert svc.calls == 1
    assert "not seen on open" in result["blockers"][0]


def test_verify_submit_final_pass_submits_clean_pins() -> None:

    class _Svc:
        store = None

        def __init__(self) -> None:
            self.rounds = 0

        def entry_batch_verify(self, body: Any) -> dict[str, Any]:
            self.rounds += 1
            by_key = {ea.canonical_key: ea for ea in body.entity_aliases}
            if "BAD" not in by_key:
                return {"ok": True, "preview_token": "tok", "warnings": []}
            aliases = {
                pin.alias_value
                for pin in by_key["BAD"].aliases
                if not getattr(pin, "remove", False)
            }
            if "OID1" in aliases:
                return {
                    "ok": False,
                    "blockers": ["Optic competitor OID1 not in active epl fixtures."],
                }
            if "BAD" in aliases:
                return {
                    "ok": False,
                    "blockers": ["px code BAD rejected for epl."],
                }
            if "poly1" in aliases:
                return {
                    "ok": False,
                    "blockers": ["polymarket_usa poly1 is live as 'P', not 'Q'."],
                }
            return {
                "ok": False,
                "blockers": ["px code BAD not seen on open markets for epl."],
            }

        def entry_batch_submit(self, token: str, actor: Any) -> dict[str, str]:
            return {"ref": "prop_partial"}

    pins = [
        {
            "league": "epl",
            "canonical_key": "BAD",
            "aliases": [
                {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OID1"},
                {"sportsbook": "px", "alias_kind": "code", "alias_value": "BAD"},
                {"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "poly1"},
            ],
        },
        {
            "league": "nhl",
            "canonical_key": "ARS",
            "aliases": [{"sportsbook": "px", "alias_kind": "code", "alias_value": "ARS"}],
        },
    ]
    svc = _Svc()
    result = verify_submit(svc, _admin(), pins, [], True, "note")
    assert result["ok"] is True
    assert result["review"]["ref"] == "prop_partial"
    assert result["count"] == 1
    assert svc.rounds >= 3


def test_drop_implicated_dry_run_fail_scoped_by_league() -> None:
    pins = [
        {
            "league": "epl",
            "canonical_key": "VAL",
            "aliases": [{"alias_value": "VCF"}],
        },
        {
            "league": "la_liga",
            "canonical_key": "VAL",
            "aliases": [{"alias_value": "VCF"}],
        },
    ]
    kept, _dropped = _drop_implicated(
        pins,
        ["entity_alias dry-run failed for VAL (epl): ['collision']"],
    )
    assert [pin["league"] for pin in kept] == ["la_liga"]


def test_verify_submit_noop_when_already_live() -> None:

    class _Svc:
        store = None

        def entry_batch_verify(self, body: Any) -> dict[str, Any]:
            return {
                "ok": False,
                "blockers": ["All proposed changes already match current rules."],
            }

    result = verify_submit(
        _Svc(),
        _admin(),
        [_crypto_alias_pin("VAL", "Valencia", "ok-id")],
        [],
        True,
        "note",
    )
    assert result["ok"] is True
    assert result.get("noop") is True
    assert result["count"] == 1


def test_drop_implicated_strips_all_optic_on_multi_id_name_mismatch() -> None:
    pin = {
        "canonical_name": "Team",
        "aliases": [
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OID1"},
            {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "OID2"},
            {"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "88001"},
        ],
    }
    kept, _dropped = _drop_implicated(
        [pin],
        ["Optic OID1 is 'Live A', not 'Team'."],
    )
    assert len(kept) == 1
    books = {alias["sportsbook"] for alias in kept[0]["aliases"]}
    assert books == {"crypto.com"}


def test_verify_submit_drops_league_blocker_pin() -> None:

    class _Svc:
        store = None

        def __init__(self) -> None:
            self.n = 0

        def entry_batch_verify(self, body: Any) -> dict[str, Any]:
            self.n += 1
            if self.n == 1:
                return {
                    "ok": False,
                    "blockers": ["px code CHE rejected for uefa_womens_champions_league."],
                }
            return {"ok": True, "preview_token": "tok", "warnings": []}

        def entry_batch_submit(self, token: str, actor: Any) -> dict[str, str]:
            return {"ref": "prop_ok"}

    pins = [
        {
            "league": "uefa_womens_champions_league",
            "canonical_key": "CHE",
            "aliases": [{"sportsbook": "px", "alias_kind": "code", "alias_value": "CHE"}],
        },
        {
            "league": "nhl",
            "canonical_key": "BOS",
            "aliases": [{"sportsbook": "polymarket_usa", "alias_kind": "code", "alias_value": "bosbru"}],
        },
    ]
    result = verify_submit(_Svc(), _admin(), pins, [], True, "note")
    assert result["ok"] is True
    assert result["review"]["ref"] == "prop_ok"


def test_drop_implicated_keeps_clone_pins_on_generic_blocker() -> None:
    onboard = {
        "kind": "mapping_league",
        "league": "new_cup",
        "clone_market_rules_from": "epl",
    }
    existing = {
        "kind": "mapping_league",
        "league": "sri_lanka_t20_major_clubs",
        "clone_market_rules_from": "psl",
    }
    kept, _dropped = _drop_implicated(
        [onboard, existing, {"aliases": [{"alias_value": "VAL"}]}],
        ["clone_market_rules_from is only valid when adding a new league"],
    )
    slugs = [pin.get("league") for pin in kept if pin.get("kind") == "mapping_league"]
    assert slugs == ["new_cup", "sri_lanka_t20_major_clubs"]


def test_drop_clone_on_existing_strips_tip_slug() -> None:
    store = SimpleNamespace(
        current_rule_set_id="r1",
        leagues_for=lambda _rid: [SimpleNamespace(league="epl")],
    )
    out = drop_clone_on_existing(store, [
        {"kind": "mapping_league", "league": "EPL", "clone_market_rules_from": "la_liga"},
        {"kind": "mapping_league", "league": "new_cup", "clone_market_rules_from": "epl"},
    ])
    assert out[0]["clone_market_rules_from"] is None
    assert out[1]["clone_market_rules_from"] == "epl"
