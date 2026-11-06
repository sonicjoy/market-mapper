"""SX team names no name rule fits, pinned to the Optic competitor id they name.

SX matching takes a fixture only when BOTH team names land (``sxbet_pass``; no one-name "anchored" fallback since
2026-10-14). A club SX spells too differently for the rules ("Excelsior Rotterdam" / Optic "SBV Excelsior") would
leave its event unmapped; a pin here closes it by Optic id instead of by guessing. Each pin is reviewed in an MR and
carries its evidence: the Optic fixture both clubs were on, where SX's other team already landed by name and the
kickoff second matched. Optic ids are the same in test and prod; Optic keeps per-competition competitors, so one
club can carry two ids.

Measured 2026-10-14 (prod inputs, ten leagues): these 17 names were the only gap between the one-name rule and the
both-names rule -- every one of them a correct pairing.
"""

from __future__ import annotations

OPTIC_IDS_BY_SX_NAME: dict[str, frozenset[str]] = {
    name.casefold(): frozenset(ids)
    for name, ids in (
        # argentina_primera
        # 202610181A68FAA3, Optic "CA Gimnasia y Esgrima de Mendoza"
        ("Atletico Gimnasia y Esgrima de Mendoza", ("914A718F776A36CE",)),
        ("Club Atletico Independiente Avellaneda", ("0694F7D55888",)),  # 2026101873ED341A "CA Independiente"
        ("Atletico Tucuman", ("A7E6EF4755F5",)),  # 20261018870E1F79 "CA Tucumán"
        ("Club Atlético Tigre", ("DC3D928134C5",)),  # 20261018C5246AF7 "CA Tigre"
        ("Club Atletico River Plate Argentina", ("38FDA3B68CF2",)),  # 20261018CCBB87EF "CA River Plate"
        ("Club Atletico Sarmiento De Junin", ("64718C29F7FD",)),  # 20261018EBB0814B "CA Sarmiento"
        ("Deportivo Riestra", ("A08FA7D7EF43",)),  # 20261018F70975B3 "CD Riestra"
        # germany_bundesliga
        ("FC Bayern Munich", ("0902C2B2E3B2",)),  # 202610171F6D432B "FC Bayern München"
        ("Sport-Club Freiburg", ("2C4C711AE917",)),  # 20261018F2FDA804 "SC Freiburg"
        # liga_mx
        # 2026101709F72A09, Optic "Pumas de la Universidad Nacional Autonoma de Mexico"
        ("Pumas UNAM", ("A3DA6E9D1669",)),
        ("Atlas Guadalajara", ("DF9AF28C07E7",)),  # 2026101744395B0C "Atlas FC"
        ("C.F. Pachuca", ("5BB6E729822B",)),  # 2026101935886DE1 "CF Pachuca"
        # ncaaf
        ("University Of Alabama Birmingham Blazers", ("0AD964BA2FEC",)),  # 20261015F7E7134C "UAB"
        # netherlands_eredivisie
        ("Excelsior Rotterdam", ("4DEB5BDF207E",)),  # 2026101689BA7FFC "SBV Excelsior"
        ("NEC Nijmegen", ("85E51B3E5D6C",)),  # 2026101782CACA6F "Nijmegen Eendracht Combinatie"
        ("AZ Alkmaar", ("F7A33FA004CA",)),  # 202610189F527A43 "Alkmaar Zaanstreek"
        # super_lig
        ("Kasimpasa", ("1286A5927809",)),  # 20261018CE640B56 "Kasımpaşa Spor Kulübü"
    )
}


def pinned_side(sx_name: str, team_map: dict[str, str]) -> str | None:
    """The fixture side a pinned SX name names, via its Optic competitor id; None when unpinned or ambiguous.

    ``team_map`` is the fixture's ``{optic_team_id: side}``; ids that hit no side, or both, are no side.
    """
    ids = OPTIC_IDS_BY_SX_NAME.get(sx_name.strip().casefold(), frozenset())
    sides = {team_map[i] for i in ids if i in team_map}
    return sides.pop() if len(sides) == 1 else None
