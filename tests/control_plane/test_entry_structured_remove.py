"""Rules-driven alias removal verify (structured + remove=True)."""

from __future__ import annotations

from mappers.control_plane.entry import ACK_RULES_WRITE
from mappers.control_plane.entry_structured import verify_structured_alias
from mappers.control_plane.store import EntityRow


def _trevor() -> EntityRow:
    return EntityRow(
        league="atp",
        entity_type="team",
        canonical_key="SVA2",
        canonical_name="Trevor Svajda",
        aliases=[
            {
                "sportsbook": "kalshi",
                "alias_kind": "code",
                "alias_value": "SVA",
                "enabled": True,
            },
            {
                "sportsbook": "kalshi",
                "alias_kind": "code",
                "alias_value": "SVA2",
                "enabled": True,
            },
        ],
        enabled=True,
    )


def test_structured_remove_ok() -> None:
    out = verify_structured_alias(
        league="atp",
        sportsbook="kalshi",
        alias_kind="code",
        alias_value="SVA",
        entity_type="team",
        canonical_key="SVA2",
        provided_name="Trevor Svajda",
        note=None,
        acknowledge_shadow=True,
        entities=[_trevor()],
        remove=True,
    )
    assert out["ok"] is True
    assert "Remove" in out["preview"]["summary"]
    assert out["payload"]["aliases"][0]["remove"] is True


def test_structured_remove_blocks_when_not_live() -> None:
    out = verify_structured_alias(
        league="atp",
        sportsbook="kalshi",
        alias_kind="code",
        alias_value="MISSING",
        entity_type="team",
        canonical_key="SVA2",
        provided_name="Trevor Svajda",
        note=None,
        acknowledge_shadow=True,
        entities=[_trevor()],
        remove=True,
    )
    assert out["ok"] is False
    assert out["blockers"]


def test_structured_remove_requires_shadow_ack() -> None:
    out = verify_structured_alias(
        league="atp",
        sportsbook="kalshi",
        alias_kind="code",
        alias_value="SVA",
        entity_type="team",
        canonical_key="SVA2",
        provided_name="Trevor Svajda",
        note=None,
        acknowledge_shadow=False,
        entities=[_trevor()],
        remove=True,
    )
    assert out["ok"] is False
    assert ACK_RULES_WRITE in out["blockers"]
