"""Pin building for scripts/submit_dkex_name_aliases.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from mappers.control_plane.rows import EntityRow

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "submit_dkex_name_aliases.py"
_SPEC = importlib.util.spec_from_file_location("submit_dkex_name_aliases", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script)

WOLVES_OPTIC = "94CB52205FE40CB1"


def _team(league: str, key: str, *aliases: tuple[str, str, str], tombstone: bool = False) -> EntityRow:
    return EntityRow(
        league=league, entity_type="team", canonical_key=key, canonical_name=key,
        aliases=[{"sportsbook": b, "alias_kind": k, "alias_value": v, "enabled": True}
                 for b, k, v in aliases],
        tombstone=tombstone,
    )


def _pins(entities: list[EntityRow]) -> dict[tuple[str, str], str]:
    payloads, _ = script.payloads_for(entities)
    return {(p.league, p.aliases[0].alias_value): p.canonical_key for p in payloads}


def test_key_is_resolved_from_the_optic_id_not_assumed() -> None:
    """Prod keys Wolves WWF7, test WOL: whichever tip is read decides."""
    for key in ("WWF7", "WOL"):
        wolves = _team("england_championship", key, ("optic", "external_id", WOLVES_OPTIC))
        assert _pins([wolves])[("england_championship", "Wolves")] == key


def test_pin_is_a_dkex_name_alias_only() -> None:
    wolves = _team("england_championship", "WOL", ("optic", "external_id", WOLVES_OPTIC))
    payloads, _ = script.payloads_for([wolves])
    (pin,) = [a for p in payloads for a in p.aliases]
    assert (pin.sportsbook, pin.alias_kind, pin.alias_value) == ("dkex", "name", "Wolves")


def test_a_team_the_tip_lacks_is_skipped_not_created() -> None:
    payloads, skipped = script.payloads_for([])
    assert payloads == []
    assert len(skipped) == len(script.NAMES)


def test_the_optic_id_counts_only_in_its_own_league() -> None:
    elsewhere = _team("epl", "WOL", ("optic", "external_id", WOLVES_OPTIC))
    assert ("england_championship", "Wolves") not in _pins([elsewhere])


def test_tombstoned_or_ambiguous_owners_are_skipped() -> None:
    dead = _team("england_championship", "WOL", ("optic", "external_id", WOLVES_OPTIC), tombstone=True)
    assert ("england_championship", "Wolves") not in _pins([dead])
    twins = [_team("england_championship", k, ("optic", "external_id", WOLVES_OPTIC)) for k in ("A", "B")]
    assert ("england_championship", "Wolves") not in _pins(twins)


def test_name_already_on_another_team_is_not_moved() -> None:
    wolves = _team("england_championship", "WOL", ("optic", "external_id", WOLVES_OPTIC))
    other = _team("england_championship", "XXX", ("dkex", "name", "Wolves"))
    payloads, skipped = script.payloads_for([wolves, other])
    assert ("england_championship", "Wolves") not in {(p.league, p.aliases[0].alias_value) for p in payloads}
    assert any("already a dkex name on ['XXX']" in s for s in skipped)


def test_name_already_pinned_is_not_repinned() -> None:
    wolves = _team("england_championship", "WOL", ("optic", "external_id", WOLVES_OPTIC),
                   ("dkex", "name", "Wolves"))
    assert ("england_championship", "Wolves") not in _pins([wolves])
