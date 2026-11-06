"""Console verify attaches live evidence_refs when the probe passes."""

from __future__ import annotations

from mappers.control_plane.live_evidence import EvidenceHit
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    BatchEntryRequest,
    EntityAliasPayload,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import EntityRow, InMemoryStore, LeagueRow


def _admin() -> Actor:
    return Actor(subject="admin@wsd.com", role=ActorRole.ADMIN)


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_ev_entry",
        entities=[
            EntityRow(
                league="boxing_matches",
                entity_type="fighter",
                canonical_key="SERRAN",
                canonical_name="Amanda Serrano",
                aliases=[],
            ),
        ],
        leagues=[
            LeagueRow(
                league="boxing_matches",
                sport="boxing",
                optic_league_id="boxing_matches",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[{
                    "sportsbook": "px",
                    "source_league_id": "1234",
                    "parser_profile": "px_generic_v1",
                }],
            )
        ],
        activate=True,
    )
    return store


def _hit(_store: object, **kw: object) -> EvidenceHit:
    value = str(kw.get("alias_value") or "")
    return EvidenceHit(refs=("px:name:Amanda Serrano", f"px:code:{value}"))


def _miss(_store: object, **kw: object) -> EvidenceHit:
    return EvidenceHit(blocker="not seen live")


def _empty_hit(_store: object, **kw: object) -> EvidenceHit:
    return EvidenceHit()


def test_structured_verify_attaches_refs() -> None:
    from mappers.control_plane.models import StructuredAliasEntryRequest

    svc = ProposalService(_store(), evidence_fn=_hit)
    body = StructuredAliasEntryRequest(
        league="boxing_matches",
        sportsbook="px",
        alias_value="SERRAN",
        provided_name="Amanda Serrano",
        entity_type="fighter",
        alias_kind="code",
        acknowledge_shadow=True,
    )
    verified = svc.entry_alias_structured_verify(body)
    assert verified["ok"] is True
    assert "px:name:Amanda Serrano" in verified["preview"]["evidence"]
    card = svc.entry_submit(verified["preview_token"], _admin())
    assert "px:name:Amanda Serrano" in card["evidence"]


def test_structured_verify_miss_is_hard_block() -> None:
    from mappers.control_plane.models import StructuredAliasEntryRequest

    svc = ProposalService(_store(), evidence_fn=_miss)
    body = StructuredAliasEntryRequest(
        league="boxing_matches",
        sportsbook="px",
        alias_value="SERRAN",
        provided_name="Amanda Serrano",
        entity_type="fighter",
        alias_kind="code",
        acknowledge_shadow=True,
    )
    verified = svc.entry_alias_structured_verify(body)
    assert verified["ok"] is False
    assert "not seen live" in verified["blockers"]
    assert verified["preview_token"] is None


def test_batch_verify_attaches_refs() -> None:
    svc = ProposalService(_store(), evidence_fn=_hit)
    body = BatchEntryRequest(
        entity_aliases=[
            EntityAliasPayload(
                league="boxing_matches",
                canonical_key="SERRAN",
                entity_type="fighter",
                canonical_name="Amanda Serrano",
                aliases=[
                    AliasPin(sportsbook="px", alias_kind="code", alias_value="SERRAN"),
                ],
            ),
        ],
        acknowledge_shadow=True,
    )
    verified = svc.entry_batch_verify(body)
    assert verified["ok"] is True
    assert "px:name:Amanda Serrano" in verified["preview"]["evidence"]
    card = svc.entry_batch_submit(verified["preview_token"], _admin())
    assert "px:name:Amanda Serrano" in card["evidence"]


def test_batch_verify_keeps_harvest_source_refs() -> None:
    svc = ProposalService(_store(), evidence_fn=_empty_hit)
    body = BatchEntryRequest(
        entity_aliases=[
            EntityAliasPayload(
                league="boxing_matches",
                canonical_key="SERRAN",
                entity_type="fighter",
                canonical_name="Amanda Serrano",
                aliases=[
                    AliasPin(
                        sportsbook="polymarket",
                        alias_kind="name",
                        alias_value="Amanda Serrano",
                    ),
                ],
                evidence_refs=[
                    "source:sport:boxing",
                    "source:league:Boxing matches (boxing_matches)",
                    "polymarket:question:Amanda Serrano vs. Opponent",
                    "polymarket:market:moneyline",
                ],
            ),
        ],
        acknowledge_shadow=True,
    )
    verified = svc.entry_batch_verify(body)
    assert verified["ok"] is True
    evidence = verified["preview"]["evidence"]
    assert "source:sport:boxing" in evidence
    assert "source:league:Boxing matches (boxing_matches)" in evidence
    assert "polymarket:question:Amanda Serrano vs. Opponent" in evidence
    assert "polymarket:market:moneyline" in evidence


def test_batch_verify_probes_every_alias() -> None:
    calls: list[str] = []

    def probe(_store: object, *, alias_value: str, **_k: object) -> EvidenceHit:
        calls.append(alias_value)
        return EvidenceHit(refs=(f"px:code:{alias_value}",))

    def payload(value: str) -> EntityAliasPayload:
        return EntityAliasPayload(
            league="boxing_matches",
            canonical_key="SERRAN",
            entity_type="fighter",
            canonical_name="Amanda Serrano",
            aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value=value)],
        )

    svc = ProposalService(_store(), evidence_fn=probe)
    verified = svc.entry_batch_verify(
        BatchEntryRequest(
            entity_aliases=[payload("A"), payload("B"), payload("C")],
            acknowledge_shadow=True,
        ),
    )
    assert verified["ok"] is True
    assert calls == ["A", "B", "C"]
