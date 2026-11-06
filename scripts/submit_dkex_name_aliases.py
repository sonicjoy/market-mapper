#!/usr/bin/env python
"""Pin DKEX team display names the DKEX pass cannot fit onto Optic's.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

DKEX writes the everyday name (``UConn``, ``Wolves``, ``Cologne``) where
Optic writes the official one (``Connecticut``, ``Wolverhampton Wanderers
FC``, ``1. FC Köln``); neither ``team_side_for`` rule can join them, so
the whole game goes unmatched.  The pass tries a ``(dkex, name)`` tip
alias first.  Each pin below was measured on the staging book of
2026-09-29 against Optic the same day: the DKEX event's other team fit,
and the Optic fixture is recorded as evidence.

The canonical key is resolved per environment from the Optic competitor
id (keys differ between test and prod); a team the target tip does not
carry is skipped and reported, never created.

    python scripts/submit_dkex_name_aliases.py --env test
    python scripts/submit_dkex_name_aliases.py --submit --env test
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    BatchEntryRequest,
    EntityAliasPayload,
)
from mappers.control_plane.rows import EntityRow
from mappers.control_plane.service import ProposalService

NOTE = (
    "2026-09-29 dkex: pin DKEX team display names that no name rule fits "
    "onto the Optic entity (staging book vs Optic, same day)."
)

# (league, DKEX participant name, Optic competitor id, Optic fixture id)
NAMES: tuple[tuple[str, str, str, str], ...] = (
    ("ncaaf", "UConn", "A273A3133F39", "202610039BD21BC3"),
    ("ncaaf", "UMass", "C3DB5719FDE6", "20261003CD6FAB1B"),
    ("ncaaf", "Georgia Bulldogs", "04C37B5D7034", "20261003664393DD"),
    ("ncaaf", "Miami OH", "1788A761CD62", "2026100364F93E5F"),
    ("ncaaf", "Miami FL", "412D810EA674", "20261003396D0662"),
    ("england_championship", "Wolves", "94CB52205FE40CB1", "202610107FAE14ED"),
    ("germany_bundesliga", "Cologne", "743038E111E7", "20261011F2AE7F40"),
    ("germany_bundesliga", "RB Leipzig", "23643B23434A", "202610102B0C44A0"),
    ("italy_serie_a", "Monza Brianza", "E7387B29ADEA", "20261011841DC9E7"),
    ("france_ligue_1", "Paris St-Germain", "6CE2C0F47875", "2026101020672937"),
    ("france_ligue_1", "Auxerre", "A4308EBB94DA", "2026101881477B69"),
    ("france_ligue_1", "Stade Rennes", "C9C064312E88", "202610110AFA3EAC"),
    ("europa_league", "Sparta Prague", "79891BC6EE01", "20261015702CEFDC"),
    ("europa_league", "AZ Alkmaar", "2ED2D66DA3BB", "202610154CDF2251"),
    ("europa_league", "Stade Rennes", "A7C018E79716", "20261015AD5EE4BD"),
    ("europa_league", "OFI Crete", "F1D467111C602536", "20261015AD5EE4BD"),
    ("brazil_serie_a", "Sao Paulo", "ED1D58650278", "202610027D2F55E6"),
    ("brazil_serie_a", "Remo Belem", "ED5DD8FBB720954A", "202610079CD9DD84"),
    ("brazil_serie_a", "Vitoria Salvador", "AC171558B6FF", "20261007195BE6F5"),
    ("brazil_serie_a", "Internacional RS", "E132F56A7003", "20261007B22A8BBE"),
    ("brazil_serie_a", "Atl Paranaense", "83831C785BD4", "20261008D22DB070"),
    ("brazil_serie_a", "Botafogo RJ", "E7282CC46B95", "20261007F7D9D3CA"),
    ("argentina_primera", "Atletico Tucuman", "A7E6EF4755F5", "20261004EED2D0A4"),
    ("argentina_primera", "Deportivo Riestra", "A08FA7D7EF43", "20261004249D5F7C"),
)


def _optic_ids(row: EntityRow) -> set[str]:
    return {
        str(a.get("alias_value") or "")
        for a in row.aliases
        if a.get("sportsbook") == "optic" and a.get("alias_kind") == "external_id"
        and a.get("enabled", True) is not False
    }


def _dkex_names(row: EntityRow) -> set[str]:
    return {
        str(a.get("alias_value") or "").casefold()
        for a in row.aliases
        if a.get("sportsbook") == "dkex" and a.get("alias_kind") == "name"
        and a.get("enabled", True) is not False
    }


def payloads_for(
    entities: list[EntityRow],
) -> tuple[list[EntityAliasPayload], list[str]]:
    """Alias payloads for the tip's entities, plus why any pin was skipped."""
    live = [e for e in entities if not e.tombstone and e.entity_type == "team"]
    out: list[EntityAliasPayload] = []
    skipped: list[str] = []
    for league, name, optic_id, fixture in NAMES:
        in_league = [e for e in live if e.league == league]
        owners = [e for e in in_league if optic_id in _optic_ids(e)]
        if len(owners) != 1:
            skipped.append(f"{league} {name!r}: {len(owners)} entities carry optic id {optic_id}")
            continue
        owner = owners[0]
        taken = [e.canonical_key for e in in_league
                 if e is not owner and name.casefold() in _dkex_names(e)]
        if taken:
            skipped.append(f"{league} {name!r}: already a dkex name on {taken}")
            continue
        if name.casefold() in _dkex_names(owner):
            skipped.append(f"{league} {name!r}: already on {owner.canonical_key}")
            continue
        out.append(EntityAliasPayload(
            league=league,
            canonical_key=owner.canonical_key,
            entity_type="team",
            canonical_name=owner.canonical_name,
            aliases=[AliasPin(sportsbook="dkex", alias_kind="name", alias_value=name)],
            evidence_refs=[f"optic:competitor:{optic_id}", f"optic:fixture:{fixture}"],
        ))
    return out, skipped


def _project(env: str) -> str:
    return "marketmaking-test" if env == "test" else "rs-marketmaking"


def _store(project: str) -> BigQueryStore:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    return BigQueryStore(
        bigquery.Client(project=project), environment=environment, allow_activate=False,
    )


def run_env(env: str, *, submit: bool) -> dict[str, Any]:
    project = _project(env)
    store = _store(project)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    payloads, skipped = payloads_for(store.entities_for(current))
    result: dict[str, Any] = {
        "project": project,
        "rule_set_id": current,
        "pins": [(p.league, p.canonical_key, p.aliases[0].alias_value) for p in payloads],
        "skipped": skipped,
    }
    if not submit or not payloads:
        return result
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_dkex_name_aliases", role=ActorRole.PROPOSER)
    body = BatchEntryRequest(entity_aliases=payloads, acknowledge_shadow=True, note=NOTE)
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    result["ref"] = str(card.get("ref") or card.get("proposal_id") or "")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true", help="file the review card")
    parser.add_argument("--env", choices=("test", "prod"), required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run_env(args.env, submit=args.submit), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
