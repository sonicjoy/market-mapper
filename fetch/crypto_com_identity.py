"""Fixture identity for crypto.com catalogue synthesis.

Prefer feed-published EXTERNAL_HOME_ID / EXTERNAL_AWAY_ID (security_def).
Live fetch never invents home/away from meta_name / security_desc text order —
UFC listing order is not reliably Home vs Away.  Unseeded fixtures are dropped.
"""

from __future__ import annotations


def symbol_prefix(symbol: str | None) -> str | None:
    """Fixture key shared by every contract of a game: league-event-date."""
    if not symbol:
        return None
    # legacy: ticker parse — replace with the typed venue field, do not extend
    parts = symbol.split("-")
    if len(parts) < 4:
        return None
    return "-".join(parts[:3])


def build_identity_index(contracts: list[dict]) -> dict[str, dict]:
    """Map each fixture's symbol prefix to its team/game identity fields.

    UFC Fight Line rows often omit EXTERNAL_GAME_ID while carrying both
    fighter ids; synthesize the game id from the NX.F.OPT symbol prefix
    (same key the underlying catalogue uses for soccer Game Lines).
    """
    index: dict[str, dict] = {}
    for c in contracts:
        prefix = symbol_prefix(c.get("Symbol"))
        if prefix is None or prefix in index:
            continue
        home_id = c.get("eventMetaEXTERNAL_HOME_ID")
        away_id = c.get("eventMetaEXTERNAL_AWAY_ID")
        game_id = c.get("eventMetaEXTERNAL_GAME_ID") or prefix
        if not (home_id and away_id):
            continue
        index[prefix] = {
            "eventMetaEXTERNAL_HOME_ID": home_id,
            "eventMetaEXTERNAL_AWAY_ID": away_id,
            "eventMetaEXTERNAL_GAME_ID": game_id,
            "eventMetaHOME_PARTICIPANT": c.get("eventMetaHOME_PARTICIPANT") or "",
            "eventMetaAWAY_PARTICIPANT": c.get("eventMetaAWAY_PARTICIPANT") or "",
        }
    return index
