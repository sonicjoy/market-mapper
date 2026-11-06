#!/usr/bin/env python
"""Pin Polymarket US CFB team codes that do not match Optic abbreviations.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

Official Polymarket is not touched — ``cfb`` is the US inner code on the
``polymarket_usa`` pin. Path 2 US compares gateway team abbreviations to Optic abbrs
(``ncar`` vs ``UNC``), so these pins are required for the 29 Aug cards.

    GCP_PROJECT=marketmaking-test python scripts/submit_ncaaf_cfb_usa_aliases.py
    python scripts/submit_ncaaf_cfb_usa_aliases.py --submit --env both
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from google.cloud import bigquery

from mappers.alias_kinds import optic_pin
from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    BatchChangesPayload,
    BatchEntryRequest,
    EntityAliasPayload,
)
from mappers.control_plane.service import ProposalService

NOTE = (
    "2026-08-28 ncaaf: pin polymarket_usa CFB codes that diverge from "
    "Optic abbreviations so Path 2 US can stamp the 29 Aug slate."
)

# (canonical_key, name, optic_id, usa_code, us_symbol, optic_fixture_id)
_TEAMS: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "UNC", "North Carolina", "D8E9069D0DAD", "NCAR",
        "aec-cfb-ncar-tcu-2026-08-29", "202608298B55D789",
    ),
    (
        "SJSU", "San Jose State", "BCBC3E2330D5", "SJST",
        "aec-cfb-sjst-usc-2026-08-29", "20260829718EBA5B",
    ),
    (
        "NCSU", "North Carolina State", "F68617FF3A0A", "NCST",
        "aec-cfb-ncst-vir-2026-08-29", "2026082984D3B8D0",
    ),
    (
        "UVA", "Virginia", "9F5958B05742", "VIR",
        "aec-cfb-ncst-vir-2026-08-29", "2026082984D3B8D0",
    ),
    (
        "JVST", "Jacksonville State", "9CB35232C2A0", "JAXST",
        "aec-cfb-jaxst-ndkst-2026-08-29", "20260829F3F4416E",
    ),
    (
        "NDSU", "North Dakota State", "283AD3A25745", "NDKST",
        "aec-cfb-jaxst-ndkst-2026-08-29", "20260829F3F4416E",
    ),
    (
        "SAC", "Sacramento State", "29A5D16FFEE7", "SACST",
        "aec-cfb-sacst-emich-2026-08-29", "20260829B49F2F5E",
    ),
    (
        "EMU", "Eastern Michigan", "9D16C59F9D74", "EMICH",
        "aec-cfb-sacst-emich-2026-08-29", "20260829B49F2F5E",
    ),
    (
        "HAW", "Hawaii", "AF34B381FCA9", "HAWAII",
        "aec-cfb-hawaii-stan-2026-08-29", "20260829F1540F2A",
    ),
    (
        "NMSU", "New Mexico State", "1241D7617B2E", "NMXST",
        "aec-cfb-nmxst-flst-2026-08-29", "20260829D631F836",
    ),
    (
        "FSU", "Florida State", "36D5C55CF7F1", "FLST",
        "aec-cfb-nmxst-flst-2026-08-29", "20260829D631F836",
    ),
    (
        "MEM", "Memphis", "01FBDB1511E0", "MPHS",
        "aec-cfb-mphs-unlv-2026-08-29", "20260829C47E1BEB",
    ),
)

def _usa_pin(code: str) -> AliasPin:
    return AliasPin(sportsbook="polymarket_usa", alias_kind="code", alias_value=code)


def _row_aliases(key: str, optic_id: str, usa_code: str) -> list[AliasPin]:
    pins = [
        AliasPin.model_validate(optic_pin(optic_id)),
        _usa_pin(usa_code),
    ]
    return pins


def _evidence() -> list[str]:
    refs = [
        "docs/polymarket-mapping-gaps.md",
        "gap:KXNCAAFGAME-26AUG29NCSTUVA",
    ]
    for _key, name, oid, code, ticker, fx in _TEAMS:
        refs.append(f"gap:usa:{ticker}")
        refs.append(f"optic:fixture:{fx}")
        refs.append(f"optic:competitor:{oid}:{name}:{code}")
    return refs


def build_payload() -> BatchChangesPayload:
    aliases = [
        EntityAliasPayload(
            league="ncaaf",
            canonical_key=key,
            entity_type="team",
            canonical_name=name,
            aliases=_row_aliases(key, oid, usa),
        )
        for key, name, oid, usa, _ticker, _fx in _TEAMS
    ]
    return BatchChangesPayload(entity_aliases=aliases)


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def submit_env(project: str) -> dict[str, Any]:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    current = store.current_rule_set_id
    if current is None:
        raise RuntimeError(f"{project}: no current rule set")
    payload = build_payload()
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_ncaaf_cfb_usa_aliases", role=ActorRole.PROPOSER)
    body = BatchEntryRequest(
        entity_aliases=payload.entity_aliases,
        acknowledge_shadow=True,
        note=NOTE + " " + " ".join(_evidence()),
    )
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(
            f"{project}: verify blocked: {verified.get('blockers')}",
        )
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "environment": environment,
        "rule_set_id": current,
        "alias_count": len(payload.entity_aliases),
        "keys": [row.canonical_key for row in payload.entity_aliases],
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
        "evidence_refs": _evidence(),
        "card": card,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--env",
        choices=("test", "prod", "both"),
        default="both",
        help="target environment(s) for --submit (default: both)",
    )
    args = parser.parse_args(argv)

    if args.submit:
        projects: list[str] = []
        if args.env in ("test", "both"):
            projects.append("marketmaking-test")
        if args.env in ("prod", "both"):
            projects.append("rs-marketmaking")
        results = []
        for project in projects:
            print(f"submitting {project}...", file=sys.stderr)
            results.append(submit_env(project))
        print(json.dumps(results, indent=2, default=str))
        return 0

    payload = build_payload()
    print(json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True))
    print(f"\n{len(payload.entity_aliases)} entity pin(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
