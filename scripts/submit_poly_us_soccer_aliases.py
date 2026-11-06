#!/usr/bin/env python
"""Pin Polymarket US soccer codes that diverge from Optic / Kalshi abbrs.

Legacy tip/console tool (retiring); do not ship mapping with it. Put the rule in ``mappers/vocab/*_aliases.py``.

Path 2 US matches the gateway's typed ``team.abbreviation`` to Optic abbreviations. Liga MX / NWSL / MLS
already have entities; Championship / Ireland / Uruguay / Portugal do not.

    python scripts/submit_poly_us_soccer_aliases.py
    python scripts/submit_poly_us_soccer_aliases.py --submit --env both
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
    "2026-08-29 Poly US: pin polymarket_usa soccer codes that diverge from "
    "Optic abbreviations so Path 2 can stamp live RFQ slates."
)

# league, key, name, optic_id, usa_code, ticker, fixture/game_id
_TEAMS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    (
        "liga_mx", "NCX", "Club Necaxa", "AA30D0077D7B", "NEC",
        "atc-lmx-nec-caz-2026-08-28", "AA30D0077D7B",
    ),
    (
        "liga_mx", "CAZ", "CF Cruz Azul", "9342A6591998", "CAZ",
        "atc-lmx-nec-caz-2026-08-28", "9342A6591998",
    ),
    (
        "liga_mx", "ATS", "Atlas FC", "DF9AF28C07E7", "AFT",
        "atc-lmx-aft-leo-2026-08-28", "DF9AF28C07E7",
    ),
    (
        "liga_mx", "CDG", "CD Guadalajara", "CAE317C7E908", "GUA",
        "atc-lmx-pac-gua-2026-08-29", "68138-24070-2026-08-29",
    ),
    (
        "liga_mx", "FCJ", "FC Juarez", "A8E57AA69EC1", "JU",
        "atc-lmx-tol-ju-2026-08-30", "A8E57AA69EC1",
    ),
    (
        "liga_mx", "CSL", "Club Santos Laguna", "7A5335B0D9EE", "SAN",
        "atc-lmx-san-tig-2026-08-29", "7A5335B0D9EE",
    ),
    (
        "liga_mx", "TOL", "Deportivo Toluca FC", "0F1C7BE5F63B", "TOL",
        "atc-lmx-tol-ju-2026-08-30", "0F1C7BE5F63B",
    ),
    (
        "liga_mx", "PUM", "Pumas UNAM", "A3DA6E9D1669", "PUM",
        "atc-lmx-tij-pum-2026-08-28", "A3DA6E9D1669",
    ),
    (
        "nwsl", "POR", "Portland Thorns FC", "0EA316C89B90", "THO",
        "atc-nwsl-got-tho-2026-08-28", "0EA316C89B90",
    ),
    (
        "nwsl", "SD", "San Diego Wave FC", "73B3B4553BB5", "WAV",
        "atc-nwsl-wav-rac-2026-08-28", "73B3B4553BB5",
    ),
    (
        "nwsl", "WAS", "Washington Spirit", "CE5543B38BDA", "SPI",
        "atc-nwsl-spi-bay-2026-08-30", "27362-10251-2026-08-30",
    ),
    (
        "nwsl", "BAY", "Bay FC", "125249A13981", "BAY",
        "atc-nwsl-spi-bay-2026-08-30", "27362-10251-2026-08-30",
    ),
    (
        "mls", "MIN", "Minnesota United FC", "DB878571F492", "MIM",
        "atc-mls-mia-mim-2026-08-29", "DB878571F492",
    ),
    (
        "mls", "VAN", "Vancouver Whitecaps FC", "4CF32CD3109D", "VWH",
        "atc-mls-skc-vwh-2026-08-29", "4CF32CD3109D",
    ),
    (
        "mls", "ATX", "Austin FC", "31E6E879232B", "AUS",
        "atc-mls-por-aus-2026-08-29", "31E6E879232B",
    ),
    (
        "mls", "NSH", "Nashville SC", "EB0D46B8A9C6", "NAS",
        "atc-mls-nas-fcc-2026-08-29", "EB0D46B8A9C6",
    ),
    (
        "mls", "CIN", "FC Cincinnati", "0C5FAA0D746C", "FCC",
        "atc-mls-nas-fcc-2026-08-29", "0C5FAA0D746C",
    ),
    (
        "mls", "SJ", "San Jose Earthquakes", "77D85D3D48CB", "SJE",
        "atc-mls-hou-sje-2026-08-29", "77D85D3D48CB",
    ),
    (
        "mls", "NE", "New England Revolution", "335FB1474E3A", "NER",
        "atc-mls-clb-ner-2026-08-29", "335FB1474E3A",
    ),
    (
        "england_championship", "WRE", "Wrexham FC", "EC1024AD10F28897", "WRE",
        "atc-eflch-wre-bir-2026-08-28", "EC1024AD10F28897",
    ),
    (
        "england_championship", "BIR", "Birmingham City FC", "BCA7A7EE451D", "BIR",
        "atc-eflch-wre-bir-2026-08-28", "BCA7A7EE451D",
    ),
    (
        "england_championship", "BRI", "Bristol City FC", "344FCE7747B3", "BRI",
        "atc-eflch-bri-por-2026-08-29", "344FCE7747B3",
    ),
    (
        "england_championship", "POR", "Portsmouth FC", "99557454C2E4", "POR",
        "atc-eflch-bri-por-2026-08-29", "99557454C2E4",
    ),
    (
        "ireland_premier", "DRO", "Drogheda United FC", "B34C206DADD1", "DRO",
        "atc-irlp-dro-dun-2026-08-28", "B34C206DADD1",
    ),
    (
        "ireland_premier", "DUN", "Dundalk FC", "49F94A2E97BC", "DUN",
        "atc-irlp-dro-dun-2026-08-28", "49F94A2E97BC",
    ),
    (
        "ireland_premier", "STP", "St Patrick's Athletic FC", "021FBCE24869", "STP",
        "atc-irlp-stp-wat-2026-08-28", "021FBCE24869",
    ),
    (
        "ireland_premier", "WAT", "Waterford FC", "132D86093186", "WAT",
        "atc-irlp-stp-wat-2026-08-28", "132D86093186",
    ),
    (
        "ireland_premier", "GAL", "Galway United FC", "516863B52ABD", "GAL",
        "atc-irlp-gal-she-2026-08-28", "516863B52ABD",
    ),
    (
        "ireland_premier", "SHE", "Shelbourne FC", "8E215EC77879", "SHE",
        "atc-irlp-gal-she-2026-08-28", "8E215EC77879",
    ),
    (
        "uruguay_primera_division", "MWO", "Montevideo Wanderers", "B31C4783EB58",
        "WAN", "atc-uru1-wan-esp-2026-08-28", "B31C4783EB58",
    ),
    (
        "uruguay_primera_division", "CEF", "Central Espanol FC", "F9BB308007BF7F9F",
        "ESP", "atc-uru1-wan-esp-2026-08-28", "F9BB308007BF7F9F",
    ),
    (
        "portugal_primeira_liga", "BEN", "SL Benfica", "56559155E226", "BEN",
        "atc-ligpor-ben-est-2026-08-31", "56559155E226",
    ),
    (
        "portugal_primeira_liga", "EST", "GD Estoril Praia", "82ABAB82967F", "EST",
        "atc-ligpor-ben-est-2026-08-31", "82ABAB82967F",
    ),
    (
        "portugal_primeira_liga", "ARO", "FC Arouca", "7A8262DADD5C", "ARO",
        "atc-ligpor-aro-csm-2026-08-29", "7A8262DADD5C",
    ),
    (
        "portugal_primeira_liga", "CSM", "CS Maritimo Funchal", "7AE92BC7568E3EAE",
        "CSM", "atc-ligpor-aro-csm-2026-08-29", "7AE92BC7568E3EAE",
    ),
)


def _usa_pin(code: str) -> AliasPin:
    return AliasPin(sportsbook="polymarket_usa", alias_kind="code", alias_value=code)


def _row_aliases(oid: str, usa_code: str) -> list[AliasPin]:
    return [AliasPin.model_validate(optic_pin(oid)), _usa_pin(usa_code)]


def _evidence() -> list[str]:
    refs = ["docs/polymarket-mapping-gaps.md"]
    for league, key, name, oid, code, ticker, fx in _TEAMS:
        refs.append(f"gap:usa:{ticker}")
        refs.append(f"optic:competitor:{oid}:{name}:{code}:{league}:{key}")
        refs.append(f"optic:fixture:{fx}")
    return refs


def build_payload() -> BatchChangesPayload:
    aliases = [
        EntityAliasPayload(
            league=league,
            canonical_key=key,
            entity_type="team",
            canonical_name=name,
            aliases=_row_aliases(oid, usa),
        )
        for league, key, name, oid, usa, _ticker, _fx in _TEAMS
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
    actor = Actor(subject="scripts/submit_poly_us_soccer_aliases", role=ActorRole.PROPOSER)
    body = BatchEntryRequest(
        entity_aliases=payload.entity_aliases,
        acknowledge_shadow=True,
        note=NOTE + " " + " ".join(_evidence()),
    )
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "rule_set_id": current,
        "alias_count": len(payload.entity_aliases),
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
        "card": card,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument(
        "--env", choices=("test", "prod", "both"), default="both",
    )
    args = parser.parse_args(argv)
    if args.submit:
        projects: list[str] = []
        if args.env in ("test", "both"):
            projects.append("marketmaking-test")
        if args.env in ("prod", "both"):
            projects.append("rs-marketmaking")
        results = [submit_env(project) for project in projects]
        print(json.dumps(results, indent=2, default=str))
        return 0
    payload = build_payload()
    print(json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=True))
    print(f"\n{len(payload.entity_aliases)} entity pin(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
