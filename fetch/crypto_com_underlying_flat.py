"""Flat catalogue record synthesis from crypto_underlying_securities rows."""

from __future__ import annotations

import re

from mappers.exchanges.crypto_name_guard import feed_name_fits_team

# Player-prop lines live in the security_desc selection segment, e.g.
# "Tarik Skubal Total Pitching Strikeouts Over 8.5" or
# "Heliot Ramos Total Hits Milestone 3+".
_PROP_OVER_UNDER_RE = re.compile(r"\b(Over|Under)\s+(\d+(?:\.\d+)?)\b", re.I)
# Trailing \b after \+ fails: '+' is non-word, so use (?!\d) instead.
_PROP_MILESTONE_RE = re.compile(r"\bMilestone\s+(\d+)\+(?!\d)", re.I)

# Team-scoped yes/no game lines that resolve via participant + TEAM_ID,
# not via spread/total parsing.  FIFA "To Lift The Cup" / "To Win Bronze"
# map to TO_ADVANCE in world_cup CRYPTO and need TEAM_ID synthesis here.
_TEAM_SCOPED_TYPES = frozenset(
    {
        "To Advance",
        "To Lift The Cup",
        "To Win Bronze",
    }
)
_TOTAL_TYPES = frozenset(
    {
        "Total Goals",
        "Total Points",
        "Total Runs",
    }
)
_SPREAD_TYPES = frozenset({"Spread", "Puck Line"})


def _handicap_segment(security_desc: str | None) -> str | None:
    """Return the "{selection} {line}" segment of a security_desc.

    crypto formats security_desc as
    "{teamA} vs {teamB} ; {selection} {line} ; {venue} ; {date}", so the
    selection and its signed handicap / total always live in segment index 1.
    This segment is the single most reliable line carrier: it is populated for
    every contract group (including the +/-0.5 handicap group whose event name
    omits the line) and keeps the explicit sign that the event name can drop.
    """
    if not security_desc:
        return None
    segments = security_desc.split(" ; ")
    if len(segments) < 2:
        return None
    return segments[1].strip()


def _same_team(selection: str, fixture_name: str) -> bool:
    """Whether a selection team name refers to a fixture side.

    security_desc uses short team names for some leagues ("Fever" for
    "Indiana Fever") while the fixture sides come from meta_name in full form.
    """
    return feed_name_fits_team(selection, fixture_name)


def typed_game_line_value(contract_type: str, raw_value: object) -> float | None:
    """crypto's typed PREDICT_VALUE as a line; None for line-less contract types.

    Spreads carry the signed handicap ("-13.5" favourite, "14.5" underdog),
    totals the threshold.  Never derived from security_desc / event name.
    """
    if contract_type not in _TOTAL_TYPES | _SPREAD_TYPES or raw_value in (None, ""):
        return None
    try:
        return float(str(raw_value))
    except ValueError:
        return None


def infer_game_line_outcome(row: dict) -> tuple[str | None, float | None]:
    """Typed (PREDICT_OUTCOME_TYPE, PREDICT_VALUE) for a game-line row.

    None when crypto did not publish them; the caller alerts on those
    rather than guessing from display text.
    """
    outcome_type = row.get("meta_predict_outcome_type") or None
    contract_type = row.get("meta_predict_contract_type") or ""
    value = typed_game_line_value(contract_type, row.get("meta_predict_value"))
    if outcome_type is None:
        return None, None
    if contract_type in _TOTAL_TYPES | _SPREAD_TYPES and value is None:
        return None, None
    return outcome_type, value


def infer_player_prop_value(
    security_desc: str | None,
    event_name: str | None = None,
) -> float | None:
    """Recover a player-prop PREDICT_VALUE; see infer_player_prop_line_side."""
    value, _ = infer_player_prop_line_side(security_desc, event_name)
    return value


def infer_player_prop_line_side(
    security_desc: str | None,
    event_name: str | None = None,
) -> tuple[float | None, str | None]:
    """Recover (line, Over|Under) for a player prop from security_desc / name.

    crypto_security_def never publishes PREDICT_VALUE.  Over/Under ladders
    carry ``Over|Under <line>`` in the selection segment; milestone ladders
    carry ``Milestone N+`` (mapped as over N-0.5).  Yes/No thresholds
    (``To Get A Hit``) have no numeric line here — the mapper applies a
    fixed 0.5 via ``_FIXED_OVER_HALF``.
    """
    haystacks = (
        _handicap_segment(security_desc),
        security_desc,
        event_name,
    )
    for text in haystacks:
        if not text:
            continue
        if m := _PROP_MILESTONE_RE.search(text):
            return int(m.group(1)) - 0.5, "Over"
        if m := _PROP_OVER_UNDER_RE.search(text):
            return float(m.group(2)), m.group(1).capitalize()
    return None, None


def to_advance_team_id(
    contract_type: str,
    outcome_type: str | None,
    participant: str | None,
    home_name: str,
    away_name: str,
    identity: dict,
) -> str | None:
    """Resolve eventMetaTEAM_ID for a team-scoped game line from fixture identity."""
    if contract_type not in _TEAM_SCOPED_TYPES:
        return None
    home_id = identity.get("eventMetaEXTERNAL_HOME_ID")
    away_id = identity.get("eventMetaEXTERNAL_AWAY_ID")
    if outcome_type == "Home":
        return home_id
    if outcome_type == "Away":
        return away_id
    if participant == home_name:
        return home_id
    if participant == away_name:
        return away_id
    return None


def team_id_from_participant(
    participant: str | None,
    home_name: str | None,
    away_name: str | None,
    home_id: str | None,
    away_id: str | None,
) -> str | None:
    """Map Team Prop PARTICIPANT onto the fixture EXTERNAL_* team id."""
    part = (participant or "").strip()
    home = (home_name or "").strip()
    away = (away_name or "").strip()
    if not part or not home or not away:
        return None
    home_hit = _same_team(part, home)
    away_hit = _same_team(part, away)
    if home_hit and not away_hit:
        return home_id
    if away_hit and not home_hit:
        return away_id
    return None


def flat_catalogue_record(
    row: dict,
    identity: dict,
    *,
    outcome_type: str | None = None,
    value: float | None = None,
    team_id: str | None = None,
) -> dict:
    """One flattened catalogue record from an underlying-securities row."""
    return {
        "SecurityID": row.get("security_id"),
        "Symbol": row.get("symbol"),
        "eventMetaLEAGUE": row.get("meta_league"),
        "eventMetaSPORTS_GROUPING": row.get("meta_sports_grouping"),
        "eventMetaEVENT_DATE": row.get("meta_event_date"),
        "eventMetaPREDICT_MARKET_TYPE": row.get("meta_predict_market_type"),
        "eventMetaPREDICT_CONTRACT_TYPE": row.get("meta_predict_contract_type"),
        "eventMetaPREDICT_PERIOD_TYPE": row.get("meta_predict_period_type"),
        "eventMetaPREDICT_EVENT_TYPE": row.get("meta_predict_event_type"),
        "eventMetaPREDICT_OUTCOME_TYPE": outcome_type,
        "eventMetaPREDICT_VALUE": value,
        "eventName": row.get("meta_event_name"),
        "eventMetaPREDICT_MARKET_ID": row.get("meta_predict_market_id"),
        "eventMetaPREDICT_OUTCOME_ID": row.get("meta_predict_outcome_id"),
        "eventMetaPARTICIPANT": row.get("meta_participant"),
        "eventMetaPLAYER_ID": None,
        "eventMetaTEAM_ID": team_id,
        "fix_type": "UnderlyingCatalogue",
        "publish_time": row.get("publish_time"),
        **identity,
    }


def flat_prop_record(prop: dict, identity: dict) -> dict:
    """Player-prop flat record bridged to fixture identity.

    Recover line/side from security_desc when PREDICT_VALUE is absent
    (SecurityDef-sourced and some underlying rows).
    """
    value, outcome = infer_player_prop_line_side(
        prop.get("security_desc"),
        prop.get("meta_event_name"),
    )
    return flat_catalogue_record(
        prop,
        identity,
        outcome_type=outcome,
        value=value,
    )


def flat_game_line_record(
    row: dict,
    identity: dict,
    home_name: str,
    away_name: str,
) -> dict | None:
    """Game-line flat record, or None when outcome fields cannot be inferred."""
    outcome_type, value = infer_game_line_outcome(row)
    if outcome_type is None:
        return None
    team_id = to_advance_team_id(
        row.get("meta_predict_contract_type") or "",
        outcome_type,
        row.get("meta_participant"),
        home_name,
        away_name,
        identity,
    )
    return flat_catalogue_record(
        row,
        identity,
        outcome_type=outcome_type,
        value=value,
        team_id=team_id,
    )


def flat_game_prop_record(row: dict, identity: dict) -> dict:
    """Game-prop flat record (yes/no questions about the whole fixture)."""
    return flat_catalogue_record(row, identity, outcome_type="Yes", value=None)


def flat_team_prop_record(row: dict, identity: dict) -> dict:
    """Team-prop flat record: Over/Under line plus synthesized TEAM_ID."""
    value, outcome = infer_player_prop_line_side(
        row.get("security_desc"),
        row.get("meta_event_name"),
    )
    team_id = team_id_from_participant(
        row.get("meta_participant"),
        identity.get("eventMetaHOME_PARTICIPANT"),
        identity.get("eventMetaAWAY_PARTICIPANT"),
        identity.get("eventMetaEXTERNAL_HOME_ID"),
        identity.get("eventMetaEXTERNAL_AWAY_ID"),
    )
    return flat_catalogue_record(
        row,
        identity,
        outcome_type=outcome,
        value=value,
        team_id=team_id,
    )


def underlying_row_to_flat(
    row: dict,
    identity: dict,
) -> tuple[dict | None, str | None, str | None]:
    """Convert one underlying row to a flat record.

    Returns ``(record, market_group, skip_reason)`` where exactly one of
    ``record`` / ``skip_reason`` is set (both are None for non-mappable market
    groups we intentionally ignore).  ``skip_reason`` distinguishes:

    * ``"no_identity"`` — identity lacks HOME/AWAY_PARTICIPANT names (fail-closed;
      never invent from meta_name text order).
    * ``"unparsed_game_line"`` — teams are known but the outcome/line could not
      be inferred (a mapper gap: a bug, an unhandled contract type, or alias
      drift).  These must be alerted on, never silently dropped.

    Game-line/fight-line home/away always comes from the fixture's already
    resolved ``identity`` (HOME_PARTICIPANT/AWAY_PARTICIPANT).  Text-order
    guessing from meta_name is never used (Rakic/Tybura: listing order is not
    reliably Home vs Away).
    """
    market_group = row.get("meta_predict_market_type")
    if market_group in ("Game Line", "Fight Line"):
        return _game_or_fight_line_flat(row, identity)
    if market_group == "Player Prop":
        return flat_prop_record(row, identity), market_group, None
    if market_group == "Team Prop":
        return flat_team_prop_record(row, identity), market_group, None
    if market_group in ("Game Prop", "Fight Prop"):
        return flat_game_prop_record(row, identity), market_group, None
    return None, None, None


def _game_or_fight_line_flat(
    row: dict,
    identity: dict,
) -> tuple[dict | None, str | None, str | None]:
    """Flat Game/Fight Line record, or a skip reason."""
    market_group = row.get("meta_predict_market_type")
    home_name = identity.get("eventMetaHOME_PARTICIPANT") or None
    away_name = identity.get("eventMetaAWAY_PARTICIPANT") or None
    if not home_name or not away_name:
        return None, None, "no_identity"
    flat = flat_game_line_record(row, identity, home_name, away_name)
    if flat is None:
        return None, None, "unparsed_game_line"
    return flat, market_group, None
