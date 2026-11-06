"""Review cards attach named Optic competitor evidence."""

from __future__ import annotations

from mappers.control_plane.league_review import payload_alias_refs
from mappers.control_plane.models import (
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    ProposalRecord,
)
from mappers.control_plane.review_cards import build_review_view


def test_review_evidence_names_optic_pins() -> None:
    payload = BatchChangesPayload(
        entity_aliases=[
            EntityAliasPayload(
                league="atp",
                canonical_key="UBG9",
                canonical_name="Ugo Blanchet",
                entity_type="player",
                aliases=[
                    AliasPin(
                        sportsbook="crypto.com",
                        alias_kind="external_id",
                        alias_value="814825",
                    ),
                    AliasPin(
                        sportsbook="optic",
                        alias_kind="external_id",
                        alias_value="245B95767109",
                    ),
                ],
            ),
        ],
    )
    proposal = ProposalRecord(
        proposal_id="prop_1",
        request_id="req_1",
        status="validated",
        expected_rule_set_id="S0",
        artifact_type="batch_changes",
        summary="Batch: 1 aliases",
        evidence_refs=["gap:NX.F.OPT.TENNIS-1", "crypto:name:Ugo Blanchet"],
        work_item_id=None,
        payload=payload,
        proposer_subject="admin@wsd.com",
    )
    view = build_review_view(
        proposal,
        status="waiting_for_checker",
        changes=None,
        change_groups=None,
    )
    assert "optic:competitor:245B95767109:Ugo Blanchet" in view["evidence"]
    assert "crypto:name:Ugo Blanchet" in view["evidence"]


def test_review_shows_poly_source_details() -> None:
    payload = BatchChangesPayload(
        entity_aliases=[
            EntityAliasPayload(
                league="germany_bundesliga",
                canonical_key="RBL",
                canonical_name="RasenBallsport Leipzig",
                entity_type="team",
                aliases=[
                    AliasPin(sportsbook="polymarket", alias_kind="name", alias_value="RB Leipzig"),
                ],
                evidence_refs=["source:sport:soccer"],
                reassign=False,
            )
        ]
    )
    proposal = ProposalRecord(
        proposal_id="prop_poly",
        request_id="req_poly",
        status="validated",
        expected_rule_set_id="S0",
        artifact_type="batch_changes",
        summary="Batch: 1 aliases",
        evidence_refs=[
            "source:sport:soccer",
            "source:league:Germany Bundesliga (germany_bundesliga)",
            "polymarket:question:RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5",
            "polymarket:market:O/U 2.5",
            "optic:fixture:g1:RasenBallsport Leipzig vs Borussia Mönchengladbach (2026-08-29)",
            "optic:competitor:oid-rbl:RasenBallsport Leipzig",
        ],
        work_item_id=None,
        payload=payload,
        proposer_subject="admin@wsd.com",
    )
    assert payload_alias_refs(payload) == ["source:sport:soccer"]
    view = build_review_view(proposal, status="waiting_for_checker", changes=None, change_groups=None)
    assert "source:sport:soccer" in view["evidence"]
    assert "polymarket:question:RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5" in view["evidence"]
    assert "polymarket:market:O/U 2.5" in view["evidence"]
    assert "optic:fixture:g1:RasenBallsport Leipzig vs Borussia Mönchengladbach (2026-08-29)" in view["evidence"]


def _rotated_usa_payload() -> BatchChangesPayload:
    return BatchChangesPayload(
        entity_aliases=[
            EntityAliasPayload(
                league="bulgaria_parva_liga",
                canonical_key="DR",
                canonical_name="DR FK Dunav Ruse",
                entity_type="team",
                aliases=[
                    AliasPin(sportsbook="optic", alias_kind="external_id", alias_value="7BFFE59C91FCD0DE"),
                    AliasPin(sportsbook="polymarket_usa", alias_kind="code", alias_value="dun"),
                ],
            ),
            EntityAliasPayload(
                league="cs2",
                canonical_key="ATR7",
                canonical_name="ATR7 Atreides",
                entity_type="team",
                aliases=[
                    AliasPin(sportsbook="optic", alias_kind="external_id", alias_value="82ECCB05BBAF9851"),
                    AliasPin(sportsbook="polymarket_usa", alias_kind="code", alias_value="atr"),
                ],
            ),
            EntityAliasPayload(
                league="cs2",
                canonical_key="AZU8",
                canonical_name="AZU8 Azuolas",
                entity_type="team",
                aliases=[
                    AliasPin(sportsbook="optic", alias_kind="external_id", alias_value="C30BA00000000000"),
                    AliasPin(sportsbook="polymarket_usa", alias_kind="code", alias_value="azu"),
                ],
            ),
        ]
    )


def test_review_unrotates_interleaved_fixtures() -> None:
    payload = _rotated_usa_payload()
    proposal = ProposalRecord(
        proposal_id="prop_rot",
        request_id="req_rot",
        status="validated",
        expected_rule_set_id="S0",
        artifact_type="batch_changes",
        summary="Batch: 3 aliases",
        evidence_refs=[
            "optic:competitor:7BFFE59C91FCD0DE:FK Dunav Ruse",
            "optic:fixture:cs2-1:Atreides vs Virtus.pro (2026-08-31)",
            "optic:competitor:82ECCB05BBAF9851:Atreides",
            "optic:fixture:cs2-2:Azuolas vs Entropy (2026-08-31)",
            "optic:competitor:C30BA00000000000:Azuolas",
            "optic:fixture:pvl-1:FK Dunav Ruse vs Slavia Sofia (2026-09-07)",
        ],
        work_item_id=None,
        payload=payload,
        proposer_subject="pipeline-gap-fix",
    )
    evidence = build_review_view(
        proposal, status="waiting_for_checker", changes=None, change_groups=None,
    )["evidence"]
    assert _fixture_after_oid(evidence, "7BFFE59C91FCD0DE", "FK Dunav Ruse vs Slavia Sofia")
    assert _fixture_after_oid(evidence, "82ECCB05BBAF9851", "Atreides vs Virtus.pro")
    assert _fixture_after_oid(evidence, "C30BA00000000000", "Azuolas vs Entropy")


def _fixture_after_oid(refs: list[str], oid: str, matchup: str) -> bool:
    prefix = f"optic:competitor:{oid}"
    last = max((i for i, ref in enumerate(refs) if ref.startswith(prefix)), default=-1)
    if last < 0 or last + 1 >= len(refs):
        return False
    nxt = refs[last + 1]
    return nxt.startswith("optic:fixture:") and matchup in nxt


def test_remove_only_headline_not_update() -> None:
    payload = BatchChangesPayload(
        entity_aliases=[
            EntityAliasPayload(
                league="atp",
                canonical_key="SVA2",
                canonical_name="Trevor Svajda",
                aliases=[
                    AliasPin(
                        sportsbook="kalshi",
                        alias_kind="code",
                        alias_value="SVA",
                        remove=True,
                    )
                ],
            )
        ]
    )
    proposal = ProposalRecord(
        proposal_id="prop_rm",
        request_id="req_rm",
        status="validated",
        expected_rule_set_id="S0",
        artifact_type="batch_changes",
        summary="Remove stray SVA",
        evidence_refs=[],
        work_item_id=None,
        payload=payload,
        proposer_subject="scripts/propose_alias_removals",
    )
    snapshot = {
        "aliases": {
            "added_count": 0,
            "modified_count": 2,
            "removed_count": 0,
            "lines": ["~ Map Kalshi SVA → SVA2 Trevor Svajda (Atp)"],
        },
        "leagues": {"added_count": 0, "modified_count": 0, "removed_count": 0, "lines": []},
        "market_rules": {
            "added_count": 0,
            "modified_count": 0,
            "removed_count": 0,
            "lines": [],
        },
    }
    view = build_review_view(
        proposal,
        status="waiting_for_checker",
        changes=None,
        change_groups=snapshot,
    )
    assert view["headline"] == "Remove 1 alias."
