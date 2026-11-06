"""STX team names no exact rule fits, pinned to the Optic competitor id they name; and the one name normaliser.

A team lands on an Optic fixture side by, in order: a pin here (by Optic competitor id), the exact normalised name,
or the exact abbreviation. There is no fuzzy step and no one-team fallback: an event binds only when BOTH teams land
(``stx_fixtures``). A wrong bind is worse than an unmapped market.

Each pin is reviewed in an MR and carries its evidence: the Optic fixture at the same kickoff on which STX's other
team already landed, and the ESPN game STX links to. STX names are ESPN names with the mascot ("Indiana Hoosiers");
Optic drops the mascot ("Indiana"), and ESPN's abbreviation can differ from Optic's (IU / IND). Measured 2026-10-28
(Ontario demo v Optic REST v3; workspace ``docs/stx/data_samples/2026-10-28-mapping-trial/fixture_join.json``,
``espn_checks.json``).

Club spellings in the AFC (``The Cong-Viettel FC`` / "The Cong - Viettel") are not pinned: the competition is held.
"""

from __future__ import annotations

import re
import unicodedata

_DROPPED = re.compile(r"[.'’]")
_SEPARATORS = re.compile(r"[^a-z0-9]+")


def exact_name(name: str | None) -> str:
    """Accents folded, lower case, ``.`` ``'`` ``’`` dropped, any other non-alphanumeric run -> one space.

    "A.J. Dillon" and "AJ Dillon" agree; "Aaron Wiggins" and "Andrew Wiggins" do not. Nothing else is folded.
    """
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return _SEPARATORS.sub(" ", _DROPPED.sub("", folded)).strip()


#: (STX competition, exact_name(STX team name)) -> Optic competitor id.
OPTIC_ID_BY_STX_TEAM: dict[tuple[str, str], str] = {
    (competition, exact_name(name)): optic_id
    for competition, name, optic_id in (
        # 2026103182BC9DFC Optic "Indiana" (IND) v Minnesota, 2026-10-31 19:30Z; STX IU; ESPN 401858501
        ("NCAAF", "Indiana Hoosiers", "FCDF1C894B1B"),
        # 20261031474C54C9 Optic "Boise State" (BSU) v Texas State, 2026-11-01 02:00Z; STX BOIS; ESPN 401860908
        ("NCAAF", "Boise State Broncos", "A78B7B92E8AB"),
        # 2026102832B7EC9F New Mexico State v Optic "Jacksonville State" (JVST), 2026-10-29 00:00Z; STX JXST
        ("NCAAF", "Jacksonville State Gamecocks", "9CB35232C2A0"),
    )
}


def pinned_id(competition: str, name: str, pins: dict[tuple[str, str], str] | None = None) -> str | None:
    """The Optic competitor id a pin names for this STX team, or None when unpinned."""
    table = OPTIC_ID_BY_STX_TEAM if pins is None else pins
    return table.get((competition, exact_name(name)))
