"""Tests for AliasPin.remove stripping a live alias from the target entity."""

from __future__ import annotations

from mappers.control_plane.dry_run import apply_alias_payload, failed_dry_run_message, thin_dry_run
from mappers.control_plane.models import AliasPin, EntityAliasPayload
from mappers.control_plane.store import EntityRow


def _ent() -> EntityRow:
    return EntityRow(
        league="itf_women",
        entity_type="team",
        canonical_key="AMN8",
        canonical_name="Anna Mihalka",
        aliases=[
            {
                "sportsbook": "optic",
                "alias_kind": "external_id",
                "alias_value": "EF418FDB31BAAF16",
                "enabled": True,
            },
            {
                "sportsbook": "polymarket",
                "alias_kind": "name",
                "alias_value": "Mihalka (-1.5)",
                "enabled": True,
            },
        ],
    )


def _remove() -> EntityAliasPayload:
    return EntityAliasPayload(
        league="itf_women",
        canonical_key="AMN8",
        canonical_name="Anna Mihalka",
        aliases=[
            AliasPin(
                sportsbook="polymarket",
                alias_kind="name",
                alias_value="Mihalka (-1.5)",
                remove=True,
            ),
        ],
    )


def test_remove_pin_strips_crumb_keeps_optic() -> None:
    patched = apply_alias_payload([_ent()], _remove())
    row = next(e for e in patched if e.canonical_key == "AMN8")
    values = [a["alias_value"] for a in row.aliases]
    assert "Mihalka (-1.5)" not in values
    assert "EF418FDB31BAAF16" in values


def test_remove_pin_dry_run_ok_when_live() -> None:
    dry = thin_dry_run([_ent()], _remove())
    assert dry["ok"] is True
    assert dry["change_count"] == 1
    assert dry["alias_checks"][0]["removed"] is True
    assert dry["alias_checks"][0]["resolves_to_canonical"] is False


def test_failed_dry_run_message_includes_blocker() -> None:
    text = failed_dry_run_message({"blockers": ["All proposed changes already match current rules."]})
    assert text.startswith("thin dry-run failed: ")
    assert "already match" in text


def test_remove_pin_noop_when_already_gone() -> None:
    dry = thin_dry_run(
        [_ent()],
        EntityAliasPayload(
            league="itf_women",
            canonical_key="AMN8",
            aliases=[
                AliasPin(
                    sportsbook="polymarket",
                    alias_kind="name",
                    alias_value="Not On Tip (-1.5)",
                    remove=True,
                ),
            ],
        ),
    )
    assert dry["ok"] is False
    assert dry["blockers"]
