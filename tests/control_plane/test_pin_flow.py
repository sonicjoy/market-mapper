"""Four surfaces share one pin flow: harvest, Chat, Cart Verify, mapper join."""

from __future__ import annotations

from typing import Any

from mappers.canonical_codes import names_close, names_fit
from mappers.control_plane.chat_cart import cart_items
from mappers.control_plane.chat_pending import staged_cart_items
from mappers.control_plane.chat_session import ChatSession
from mappers.control_plane.chat_tools import ChatToolContext
from mappers.control_plane.chat_tools_propose import propose_markets
from mappers.control_plane.chat_tools_skill import stage_pin, stage_pins_from_rows
from mappers.control_plane.cow_diff import market_rule_change_counts
from mappers.control_plane.crypto_optic_match import best_fixture
from mappers.control_plane.dry_run_market_rules import thin_dry_run_market_rules
from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.live_evidence import EvidenceFetchers, EvidenceHit, probe_pin_evidence
from mappers.control_plane.models import (
    BatchEntryRequest,
    MappingMarketRulesPayload,
    MarketRuleEntryRequest,
    MarketRulePin,
)
from mappers.control_plane.official_citation import OFFICIAL_ABSENT
from mappers.control_plane.pin_flow import (
    draft_and_verify,
    draft_and_verify_remove,
    draft_pins,
    verify_pins,
)
from mappers.control_plane.pin_flow_markets import (
    draft_and_verify_market_rules,
    verify_market_pins,
)
from mappers.control_plane.pipeline_gap_card import _block_reason
from mappers.control_plane.rof_before_rule import (
    MarketRuleObservation,
    rof_before_ignore_observation,
)
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import InMemoryStore
from mappers.vocab.combat_usa import ROF_BEFORE_NOTES

_MOV_TEXT = (
    "The Underlying for this Contract is the outcome and method of victory for "
    "<competitor> in <bout> during <time period>."
)
_MOV_URL = "https://polymarket.us/contract_terms/FIGHTMETHODOFVICTORY.pdf"
_ROUNDS_TEXT = "Fight ends before round N"
_LIVE = "Juan Martin"
_OPTIC = "Juan Cruz Martin Manzano"
_OTHER = "Duje Ajdukovic"
_CID = "1528979"
_OID = "oid-jcm"


def test_names_close_not_loosened_for_middle_name() -> None:
    assert not names_close(_LIVE, _OPTIC, player=True)
    assert names_fit(_LIVE, _OPTIC, player=True)
    assert not names_fit("Rune", "Holger Rune", player=True)
    assert not names_fit("Francesco Ferrari", "Gianmarco Ferrari", player=True)
    assert names_fit("Alatengheili", "Alateng Heili", player=True)
    assert not names_fit("Smith", "Tom Jones", player=True)


def test_live_name_ok_accepts_club_bind_keys() -> None:
    from mappers.control_plane.live_evidence import _name_ok

    assert _name_ok("Ceuta", "AD Ceuta", "spain_la_liga_2")
    assert _name_ok("Bilbao", "Athletic Club Bilbao", "la_liga")
    assert _name_ok("Bayern", "Bayern Munich", "bundesliga")
    assert not _name_ok("Madrid", "Real Madrid", "la_liga")
    assert not _name_ok("Valencia", "Other Valencia", "la_liga")
    assert not _name_ok("Academy", "CTBC Flying Oyster", "cs2")


def test_names_fit_rejects_school_state_suffix() -> None:
    assert not names_fit(
        "Southern Connecticut State", "Southern Connecticut", player=False,
    )
    assert not names_fit("North Carolina State", "North Carolina", player=False)
    assert names_fit("OGC Nice", "OGC Nice Côte d'Azur", player=False)
    assert names_fit("Stade Rennais FC 1901", "Stade Rennais FC", player=False)
    assert names_fit("Hull City", "Hull City AFC", player=False)
    assert names_close("Hull City", "Hull City AFC", player=False)
    assert names_fit("Bosnia and Herzegovina", "Bosnia-Herzegovina", player=False)
    assert not names_close("Bosnia and Herzegovina", "Bosnia-Herzegovina", player=False)
    assert not names_fit("Bosnia and Herzegovina", "Bosnia", player=False)
    assert names_fit(
        "St. Vincent and the Grenadines",
        "Saint Vincent and the Grenadines",
        player=False,
    )
    assert not names_close(
        "St. Vincent and the Grenadines",
        "Saint Vincent and the Grenadines",
        player=False,
    )
    assert not names_fit(
        "St. Vincent", "Saint Vincent and the Grenadines", player=False,
    )
    assert not names_fit("North Carolina and State", "North Carolina", player=False)
    assert not names_fit("Vanderbilt Commodores", "Vanderbilt", player=False)


def test_verify_pins_keeps_px_code() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            EntityRow(
                league="epl",
                entity_type="team",
                canonical_key="HCA7",
                canonical_name="Hull City AFC",
                aliases=[],
            ),
        ],
        leagues=[],
        activate=True,
    )
    pin = {
        "kind": "entity_alias",
        "league": "epl",
        "canonical_key": "HCA7",
        "canonical_name": "Hull City AFC",
        "entity_type": "team",
        "aliases": [{"sportsbook": "px", "alias_kind": "code", "alias_value": "HUL"}],
        "evidence_refs": ["px:abbr:HUL", "optic:abbr:HCA7"],
        "reassign": False,
    }
    kept, blockers = verify_pins(store, [pin], probe=None)
    assert blockers == []
    assert kept == [pin]


def test_verify_pins_keeps_underdog_code() -> None:
    """Underdog totals pin the same alias shape Cart Verify keeps."""
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            EntityRow(
                league="nhl",
                entity_type="team",
                canonical_key="oid-fla",
                canonical_name="Florida Panthers",
                aliases=[],
            ),
        ],
        leagues=[],
        activate=True,
    )
    pin = {
        "kind": "entity_alias",
        "league": "nhl",
        "canonical_key": "oid-fla",
        "canonical_name": "Florida Panthers",
        "entity_type": "team",
        "aliases": [{"sportsbook": "underdog", "alias_kind": "code", "alias_value": "FLA"}],
        "evidence_refs": ["gap:udx:nhl:FLA"],
        "reassign": False,
    }
    kept, blockers = verify_pins(store, [pin], probe=None)
    assert blockers == []
    assert kept == [pin]


def test_verify_pins_coalesces_entities_once() -> None:
    """Cart Verify coalesces the tip once for the whole pin batch."""
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[
            EntityRow(
                league="epl",
                entity_type="team",
                canonical_key="HCA7",
                canonical_name="Hull City AFC",
                aliases=[],
            ),
        ],
        leagues=[],
        activate=True,
    )
    pin = {
        "kind": "entity_alias",
        "league": "epl",
        "canonical_key": "HCA7",
        "canonical_name": "Hull City AFC",
        "entity_type": "team",
        "aliases": [{"sportsbook": "px", "alias_kind": "code", "alias_value": "HUL"}],
        "evidence_refs": ["px:abbr:HUL"],
        "reassign": False,
    }
    calls = {"n": 0}
    orig = store.entities_for

    def wrapped(rid: str) -> Any:
        calls["n"] += 1
        return orig(rid)

    store.entities_for = wrapped  # type: ignore[method-assign]
    verify_pins(store, [pin, {**pin, "aliases": [
        {"sportsbook": "px", "alias_kind": "code", "alias_value": "AVL"},
    ]}], probe=None)
    assert calls["n"] == 1


def test_mapper_join_matches_cart_verify() -> None:
    hit = best_fixture([_optic_game()], (_LIVE, _OTHER), player=True)
    assert hit is not None
    assert hit["away_id"] == _OID


def test_draft_and_verify_keeps_tennis_legal_name() -> None:
    store = _store()
    staged = draft_and_verify(
        store, [_probe_row()], "crypto.com", probe=_probe_fn(store),
    )
    assert staged["ok"] is True
    assert staged["blockers"] == []
    pin = staged["pins"][0]
    assert pin["canonical_name"] == _OPTIC
    assert any(a.get("alias_value") == _CID for a in pin["aliases"])


def test_draft_and_verify_blocks_wrong_live_name() -> None:
    def probe(_store: object, **kw: object) -> EvidenceHit:
        return EvidenceHit(
            blocker="crypto.com 1535401 is live as 'Academy', not 'CTBC Flying Oyster'.",
        )

    staged = draft_and_verify(
        _store(), [_probe_row()], "crypto.com", probe=probe,
    )
    assert staged["ok"] is False
    assert "is live as" in staged["error"]


def test_conl_symbol_blocked_by_cart_keeps_the_gate_text() -> None:
    """NX.F.OPT.CONL refused by Cart records that sentence, not verify_blocked."""
    row = {**_probe_row(), "symbol": "NX.F.OPT.CONL-1"}
    gate = "crypto.com CONL is live as 'Other Club', not 'Home Club'."

    def probe(_store: object, **_kw: object) -> EvidenceHit:
        return EvidenceHit(blocker=gate)

    staged = draft_and_verify(_store(), [row], "crypto.com", probe=probe)
    assert staged["ok"] is False
    assert _block_reason(staged) == gate


def test_chat_stage_uses_cart_verify() -> None:
    bag = ChatSession(conversation_id="pin-flow")
    tools = ChatToolContext(_store(), bag=bag, evidence_fn=_block_probe)
    out = stage_pins_from_rows(tools, [_probe_row()], book="crypto.com")
    assert out["ok"] is False
    assert "is live as" in str(out.get("error") or "")
    assert cart_items(bag) == []


def test_harvest_draft_then_verify_agree() -> None:
    store = _store()
    pins, skipped = draft_pins(store, [_probe_row()], "crypto.com")
    assert skipped == []
    kept, blockers = verify_pins(store, pins, probe=_probe_fn(store))
    assert blockers == []
    assert kept == pins


def test_verify_remove_keeps_live_alias() -> None:
    staged = draft_and_verify_remove(_sva_store(), _remove_pin())
    assert staged["ok"] is True
    assert staged["blockers"] == []
    assert staged["pins"][0]["aliases"][0]["remove"] is True


def test_verify_remove_blocks_when_not_on_target() -> None:
    pin = _remove_pin()
    pin["aliases"][0]["alias_value"] = "MISSING"
    staged = draft_and_verify_remove(_sva_store(), pin)
    assert staged["ok"] is False
    assert "not on" in staged["error"]


def test_chat_stage_remove_uses_verify() -> None:
    bag = ChatSession(conversation_id="pin-remove")
    out = stage_pin(
        ChatToolContext(_sva_store(), bag=bag),
        league="atp",
        sportsbook="px",
        code="SVA",
        canonical_key="SVA2",
        canonical_name="Trevor Svajda",
        remove=True,
    )
    assert out["ok"] is True
    items = cart_items(bag)
    assert items[0]["payload"]["aliases"][0]["remove"] is True
    assert "Remove" in items[0]["label"]


def test_chat_stage_remove_blocks_when_not_live() -> None:
    bag = ChatSession(conversation_id="pin-remove-block")
    blocked = stage_pin(
        ChatToolContext(_sva_store(), bag=bag),
        league="atp",
        sportsbook="px",
        code="MISSING",
        canonical_key="SVA2",
        canonical_name="Trevor Svajda",
        remove=True,
    )
    assert blocked["ok"] is False
    assert cart_items(bag) == []


def _block_probe(_store: object, **_kw: object) -> EvidenceHit:
    return EvidenceHit(
        blocker=f"crypto.com {_CID} is live as {_LIVE!r}, not 'Someone Else'.",
    )


def _probe_fn(store: InMemoryStore) -> Any:
    fx = EvidenceFetchers(
        crypto_row=lambda _cid: _crypto_row(),
        optic_fixtures=lambda *_a, **_k: [_optic_game()],
    )

    def probe(inner: object, **kw: Any) -> EvidenceHit:
        kw.pop("fetchers", None)
        return probe_pin_evidence(inner or store, fetchers=fx, **kw)

    return probe


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_pin_flow",
        entities=[],
        leagues=[
            LeagueRow(
                league="atp_challenger",
                sport="tennis",
                optic_league_id="atp_challenger",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=[],
                exchanges=[],
            ),
        ],
        activate=True,
    )
    return store


def _sva_store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_sva_remove",
        entities=[
            EntityRow(
                league="atp",
                entity_type="team",
                canonical_key="SVA",
                canonical_name="Zachary Svajda",
                aliases=[
                    {"sportsbook": "px", "alias_kind": "code", "alias_value": "SVA"},
                    {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "oid-zach"},
                ],
            ),
            EntityRow(
                league="atp",
                entity_type="team",
                canonical_key="SVA2",
                canonical_name="Trevor Svajda",
                aliases=[
                    {"sportsbook": "px", "alias_kind": "code", "alias_value": "SVA"},
                    {"sportsbook": "px", "alias_kind": "code", "alias_value": "SVA2"},
                    {"sportsbook": "optic", "alias_kind": "external_id", "alias_value": "oid-trev"},
                ],
            ),
        ],
        leagues=[
            LeagueRow(
                league="atp",
                sport="tennis",
                optic_league_id="atp",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=[],
                exchanges=[],
            ),
        ],
        activate=True,
    )
    return store


def _remove_pin() -> dict[str, Any]:
    return {
        "kind": "entity_alias",
        "league": "atp",
        "canonical_key": "SVA2",
        "canonical_name": "Trevor Svajda",
        "entity_type": "team",
        "aliases": [
            {
                "sportsbook": "px",
                "alias_kind": "code",
                "alias_value": "SVA",
                "remove": True,
            }
        ],
        "evidence_refs": [
            "note:SVA belongs to Zachary Svajda (SVA); remove duplicate from Trevor Svajda.",
        ],
        "reassign": False,
    }


def _probe_row() -> dict[str, Any]:
    return {
        "symbol": "NX.F.OPT.TENNIS-0060-260902-M.0.1.1.20261231",
        "kind": "unknown_alias",
        "league": "atp_challenger",
        "crypto_ids": ["916463", _CID],
        "home_name": _OTHER,
        "away_name": _LIVE,
        "optic": {
            "home": _OTHER,
            "home_id": "oid-ajd",
            "away": _OPTIC,
            "away_id": _OID,
            "fixture_id": "fx-jcm",
        },
        "tip": [
            {"crypto_id": "916463", "owners": ["AJD"]},
            {"crypto_id": _CID, "owners": []},
        ],
        "evidence_refs": ["gap:NX.F.OPT.TENNIS-0060"],
    }


def _crypto_row() -> dict[str, Any]:
    return {
        "seen": True,
        "symbol": "NX.F.OPT.TENNIS-0060",
        "home_id": "916463",
        "home_name": _OTHER,
        "away_id": _CID,
        "away_name": _LIVE,
        "meta_name": f"{_LIVE} @ {_OTHER}",
    }


def _optic_game() -> dict[str, Any]:
    return {
        "id": "fx-jcm",
        "start_date": "2026-09-03T14:30:00Z",
        "home_competitors": [{"id": "oid-ajd", "name": _OTHER}],
        "away_competitors": [{"id": _OID, "name": _OPTIC}],
    }


def _ufc_store(rules: list[MarketRuleRow] | None = None) -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_ufc_rof",
        entities=[],
        leagues=[
            LeagueRow(
                league="ufc",
                sport="mma",
                optic_league_id="ufc",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[
                    {
                        "sportsbook": "polymarket_usa",
                        "enabled": True,
                        "parser_profile": "poly_usa_generic_v1",
                        "source_league_id": "ufc",
                        "settings": {"slug_prefix": "ufc"},
                    },
                ],
            ),
        ],
        market_rules=rules or [],
        activate=True,
    )
    return store


def _ignore_on_tip() -> MarketRuleRow:
    return MarketRuleRow(
        rule_id="mr_b7e4c1a90f2d48e6",
        league="ufc",
        sportsbook="polymarket_usa",
        rule_kind="taxonomy",
        source_key_type="ticker_suffix",
        source_key="rof-before-r",
        action="ignore",
        canonical_market_type=None,
        priority=100,
        enabled=True,
        confidence="manual",
        match_operator="prefix",
    )


def _assert_official_absent(rule: dict[str, Any]) -> None:
    blob = " ".join(
        str(rule.get(key) or "")
        for key in ("official_description", "citation_url", "notes")
    )
    assert rule["official_description"] is None
    assert rule["citation_url"] is None
    assert rule.get("confidence", "manual") == "manual"
    assert "Fight ends before" not in blob


def _usa_ignore(
    source_key: str,
    *,
    official_description: str | None = None,
    citation_url: str | None = None,
) -> MarketRuleObservation:
    obs: MarketRuleObservation = {
        "league": "ufc",
        "sportsbook": "polymarket_usa",
        "source_key": source_key,
        "source_key_type": "ticker_suffix",
        "action": "ignore",
        "notes": "trader note",
        "evidence_refs": ["polymarket_usa:contract"],
    }
    if official_description is not None:
        obs["official_description"] = official_description
    if citation_url is not None:
        obs["citation_url"] = citation_url
    return obs


def _usa_rule(pin: dict[str, Any]) -> dict[str, Any]:
    return next(
        row for row in pin.get("rules") or []
        if row.get("sportsbook") == "polymarket_usa"
    )


def test_draft_ignore_rof_before_passes_cart_dry_run() -> None:
    store = _ufc_store()
    pins, skipped = draft_and_verify_market_rules(store, [rof_before_ignore_observation()])
    assert skipped == []
    rule = _usa_rule(pins[0])
    assert rule["action"] == "ignore"
    assert rule["source_key"] == "rof-before-r"
    assert rule["match_operator"] == "prefix"
    assert rule["canonical_market_type"] is None
    assert rule["line_offset"] is None
    assert rule["yes_side"] is None
    assert rule["side_swap"] is None
    _assert_official_absent(rule)
    assert rule["notes"] == ROF_BEFORE_NOTES
    rid = store.current_rule_set_id
    assert rid is not None
    blocked = thin_dry_run_market_rules(
        list(store.leagues_for(rid)),
        [],
        MappingMarketRulesPayload(
            league="ufc",
            rules=[
                MarketRulePin(
                    sportsbook="polymarket_usa",
                    rule_kind="taxonomy",
                    source_key_type="ticker_suffix",
                    source_key="rof-before-r",
                    action="map",
                ),
            ],
        ),
    )
    assert blocked["ok"] is False


def test_cited_mov_card_keeps_the_contract_text() -> None:
    pins, skipped = draft_and_verify_market_rules(
        _ufc_store(),
        [_usa_ignore("mov", official_description=_MOV_TEXT, citation_url=_MOV_URL)],
    )
    assert skipped == []
    rule = pins[0]["rules"][0]
    assert rule["official_description"] == _MOV_TEXT
    assert rule["citation_url"] == _MOV_URL
    assert rule["confidence"] == "manual"
    assert rule["notes"] == "trader note"
    assert _MOV_TEXT not in rule["notes"]


def test_rounds_without_a_citation_stays_empty() -> None:
    pins, skipped = draft_and_verify_market_rules(_ufc_store(), [_usa_ignore("rounds")])
    assert skipped == []
    rule = pins[0]["rules"][0]
    _assert_official_absent(rule)
    assert rule["source_key"] == "rounds"


def test_rof_before_drops_an_uncited_rounds_sentence() -> None:
    obs = rof_before_ignore_observation()
    obs["official_description"] = f"{_ROUNDS_TEXT} begins"
    obs["citation_url"] = "https://example.invalid/not-polymarket-us"
    pins, skipped = draft_and_verify_market_rules(_ufc_store(), [obs])
    assert skipped == []
    rule = _usa_rule(pins[0])
    _assert_official_absent(rule)
    assert rule["notes"] == ROF_BEFORE_NOTES


def test_editor_flat_body_keeps_official_text_apart_from_notes() -> None:
    body = MarketRuleEntryRequest.model_validate(
        {
            "league": "ufc",
            "sportsbook": "polymarket_usa",
            "source_key_type": "ticker_suffix",
            "source_key": "mov",
            "action": "ignore",
            "official_description": _MOV_TEXT,
            "citation_url": _MOV_URL,
            "notes": "trader note",
        }
    )
    pin = body.rules[0]
    assert pin.action == "ignore"
    assert pin.official_description == _MOV_TEXT
    assert pin.citation_url == _MOV_URL
    assert pin.notes == "trader note"


def test_editor_verify_stamps_official_text_like_the_draft_kernel() -> None:
    service = ProposalService(_ufc_store())
    cited = service.entry_market_rule_verify(MarketRuleEntryRequest.model_validate({
        "league": "ufc",
        "sportsbook": "polymarket_usa",
        "source_key_type": "ticker_suffix",
        "source_key": "mov",
        "action": "ignore",
        "official_description": _MOV_TEXT,
        "citation_url": _MOV_URL,
        "notes": "trader note",
        "acknowledge_shadow": True,
    }))
    cited_rule = cited["payload"]["rules"][0]
    assert cited["ok"] is True
    assert cited_rule["official_description"] == _MOV_TEXT
    assert cited_rule["citation_url"] == _MOV_URL
    assert cited_rule["confidence"] == "manual"
    assert OFFICIAL_ABSENT not in cited["warnings"]
    empty = service.entry_market_rule_verify(MarketRuleEntryRequest.model_validate({
        "league": "ufc",
        "sportsbook": "polymarket_usa",
        "source_key_type": "ticker_suffix",
        "source_key": "rof-before-r",
        "action": "ignore",
        "official_description": _ROUNDS_TEXT,
        "citation_url": "https://example.invalid/not-polymarket-us",
        "notes": ROF_BEFORE_NOTES,
        "acknowledge_shadow": True,
    }))
    empty_rule = empty["payload"]["rules"][0]
    assert empty["ok"] is True
    assert empty_rule["official_description"] is None
    assert empty_rule["citation_url"] is None
    assert empty_rule["confidence"] == "manual"
    assert empty_rule["notes"] == ROF_BEFORE_NOTES
    assert OFFICIAL_ABSENT not in empty["warnings"]


def test_official_description_is_served_content_and_notes_are_not() -> None:
    base = _ignore_on_tip()
    described = MarketRuleRow(
        **{
            **base.__dict__,
            "official_description": _MOV_TEXT,
            "citation_url": _MOV_URL,
        }
    )
    noted = MarketRuleRow(**{**base.__dict__, "notes": "trader note only"})
    assert market_rule_change_counts([base], [described])["modified_count"] == 1
    assert market_rule_change_counts([base], [noted])["modified_count"] == 0


def test_draft_ignore_skips_when_tip_already_ignores() -> None:
    pins, skipped = draft_and_verify_market_rules(
        _ufc_store([_ignore_on_tip()]),
        [rof_before_ignore_observation()],
    )
    assert pins == []
    assert skipped[0]["reason"] == "already_ignored"


def test_corrective_ignore_replaces_a_prior_map() -> None:
    prior = _ignore_on_tip()
    prior.action = "map"
    prior.canonical_market_type = "total_rounds"
    pins, skipped = draft_and_verify_market_rules(
        _ufc_store([prior]),
        [rof_before_ignore_observation()],
    )
    assert skipped == []
    assert _usa_rule(pins[0])["action"] == "ignore"
    assert _usa_rule(pins[0])["canonical_market_type"] is None


def test_gap_sweeper_drafts_rof_before_when_rfq_empty() -> None:
    payload = harvest_gap_pins(
        _ufc_store(),
        inventory_fn=list,
        fixtures_fn=lambda *_args, **_kwargs: [],
    )
    rules = [
        rule
        for pin in payload["pins"]
        if pin.get("kind") == "mapping_market_rules"
        for rule in pin.get("rules") or []
        if rule.get("source_key") == "rof-before-r"
    ]
    assert len(rules) == 1
    assert rules[0]["action"] == "ignore"
    _assert_official_absent(rules[0])


def test_chat_propose_rof_before_uses_the_cart_kernel(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_propose.live_optic_census",
        lambda *_args, **_kwargs: set(),
    )
    bag = ChatSession(conversation_id="rof")
    result = propose_markets(
        _ufc_store(),
        bag,
        league="ufc",
        sportsbook="polymarket_usa",
        market="rof-before-r2",
    )
    assert result["ok"] is True
    rules = [
        rule
        for item in staged_cart_items(bag)
        for rule in (item.get("payload") or {}).get("rules") or []
        if rule.get("source_key") == "rof-before-r"
    ]
    assert len(rules) == 1
    assert rules[0]["action"] == "ignore"
    assert rules[0]["canonical_market_type"] is None
    _assert_official_absent(rules[0])


def test_chat_does_not_stage_rof_ignore_without_the_suffix(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_propose.live_optic_census",
        lambda *_args, **_kwargs: set(),
    )
    bag = ChatSession(conversation_id="plain")
    propose_markets(
        _ufc_store(), bag, league="ufc", sportsbook="polymarket_usa", market="",
    )
    keys = [
        rule.get("source_key")
        for item in staged_cart_items(bag)
        for rule in (item.get("payload") or {}).get("rules") or []
    ]
    assert "rof-before-r" not in keys


def test_description_without_a_citation_url_stays_empty() -> None:
    pins, skipped = draft_and_verify_market_rules(
        _ufc_store(),
        [_usa_ignore(
            "mov",
            official_description=_MOV_TEXT,
            citation_url="FIGHTMETHODOFVICTORY.pdf",
        )],
    )
    assert skipped == []
    rule = pins[0]["rules"][0]
    assert rule["official_description"] is None
    assert rule["citation_url"] is None
    assert rule["confidence"] == "manual"
    assert _MOV_TEXT not in (rule.get("notes") or "")


def test_cart_verify_uses_the_same_official_stamp() -> None:
    store = _ufc_store()
    drafted, _skipped = draft_and_verify_market_rules(
        store, [rof_before_ignore_observation()],
    )
    kept, skipped = verify_market_pins(store, drafted)
    assert skipped == []
    _assert_official_absent(_usa_rule(kept[0]))
    cited, _cited_skipped = draft_and_verify_market_rules(
        store,
        [_usa_ignore("mov", official_description=_MOV_TEXT, citation_url=_MOV_URL)],
    )
    kept_cited, skipped_cited = verify_market_pins(store, cited)
    assert skipped_cited == []
    assert kept_cited[0]["rules"][0]["official_description"] == _MOV_TEXT
    assert kept_cited[0]["rules"][0]["citation_url"] == _MOV_URL
    bare = {
        "kind": "mapping_market_rules",
        "league": "ufc",
        "rules": [{
            "sportsbook": "polymarket_usa",
            "rule_kind": "taxonomy",
            "source_key_type": "ticker_suffix",
            "source_key": "rof-before-r",
            "action": "ignore",
            "official_description": _ROUNDS_TEXT,
            "citation_url": "https://example.invalid/not-polymarket-us",
            "notes": ROF_BEFORE_NOTES,
        }],
    }
    kept_bare, skipped_bare = verify_market_pins(store, [bare])
    assert skipped_bare == []
    _assert_official_absent(_usa_rule(kept_bare[0]))


def test_cart_batch_verify_keeps_a_real_citation() -> None:
    service = ProposalService(_ufc_store())
    result = service.entry_batch_verify(BatchEntryRequest.model_validate({
        "acknowledge_shadow": True,
        "market_rules": [{
            "league": "ufc",
            "rules": [{
                "sportsbook": "polymarket_usa",
                "rule_kind": "taxonomy",
                "source_key_type": "ticker_suffix",
                "source_key": "mov",
                "action": "ignore",
                "official_description": _MOV_TEXT,
                "citation_url": _MOV_URL,
                "notes": "trader note",
            }],
        }],
    }))
    assert result["ok"] is True
    rule = result["payload"]["market_rules"][0]["rules"][0]
    assert rule["official_description"] == _MOV_TEXT
    assert rule["citation_url"] == _MOV_URL
    assert rule["confidence"] == "manual"
    assert _MOV_TEXT not in (rule.get("notes") or "")
    assert OFFICIAL_ABSENT not in result["warnings"]
    empty = service.entry_batch_verify(BatchEntryRequest.model_validate({
        "acknowledge_shadow": True,
        "market_rules": [{
            "league": "ufc",
            "rules": [{
                "sportsbook": "polymarket_usa",
                "rule_kind": "taxonomy",
                "source_key_type": "ticker_suffix",
                "source_key": "rof-before-r",
                "action": "ignore",
                "official_description": _ROUNDS_TEXT,
                "notes": ROF_BEFORE_NOTES,
            }],
        }],
    }))
    assert empty["ok"] is True
    empty_rule = empty["payload"]["market_rules"][0]["rules"][0]
    assert empty_rule["official_description"] is None
    assert empty_rule["citation_url"] is None
    assert empty_rule["confidence"] == "manual"
    assert empty_rule["notes"] == ROF_BEFORE_NOTES
    assert OFFICIAL_ABSENT not in empty["warnings"]
