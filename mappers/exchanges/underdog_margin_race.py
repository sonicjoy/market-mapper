"""Underdog NBA race to N points (UDXNBARACE10/20) and winning margin (series UDXNBAMOV) rows."""
import re
from collections.abc import Callable

from mappers.shared import CanonicalRow, margin_band_key

# NBA race: "Resolves Yes if the Atlanta Hawks records at least 1 the first
# attainment of at least 10 points by either team during the entire game ...".
RACE_RE = re.compile(
    r"^Resolves Yes if (?:the )?(.+?) records at least 1 the first attainment of at least "
    r"(\d+) points by either team\b",
    re.IGNORECASE,
)
# NBA winning margin: "... beat Charlotte Hornets by between 11 and 20 points in ..."
# or "... by at least 21 points in ...".
MARGIN_RE = re.compile(
    r" by (?:between (\d+) and (\d+)|at least (\d+)) points in ", re.IGNORECASE,
)


def race_rows(
    row: Callable[..., CanonicalRow], market_id: str, description: str,
    *, home: str, away: str, team: str | None,
) -> list[CanonicalRow]:
    """Race to N points, keyed like Optic (side = team, line = N).

    The N the sentence states must be the Optic id's. Someone always gets to
    10/20 in an NBA game, so (assuming a completed game) No on one team is Yes on the other.
    """
    match = RACE_RE.search(description.strip())
    if match is None or team not in {home, away}:
        return []
    if market_id != f"race_to_{match.group(2)}_points":
        return []
    target = float(match.group(2))
    opp = away if team == home else home
    return [
        row(team, entity=None, row_line=target, udx_side="yes"),
        row(opp, entity=None, row_line=target, udx_side="no"),
    ]


def margin_rows(
    row: Callable[..., CanonicalRow], description: str, team: str | None,
) -> list[CanonicalRow]:
    """Winning margin band as Optic's (team, band) Yes; "not this band" has no Optic odd."""
    match = MARGIN_RE.search(description)
    if match is None or team is None:
        return []
    low, high, open_low = match.groups()
    key = margin_band_key(int(open_low), None) if open_low else margin_band_key(int(low), int(high))
    return [row("yes", entity=team, row_line=None, udx_side="yes", grouping_key=key)]
