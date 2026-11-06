"""Shared UFC fight-prop normalization."""

from __future__ import annotations

import re

from mappers.shared import normalize_player_name

# Canonical method keys used as CanonicalRow.grouping_key.  Rows merge
# only on identical keys, so like-for-like settlement is a property of
# the key (Kalshi draw_or_nc never meets Optic draw; Kalshi ko_tko_dq
# never meets Polymarket ko_tko).
METHOD_KO_TKO_DQ = "ko_tko_dq"
METHOD_SUBMISSION = "submission"
METHOD_DECISION = "decision"
METHOD_DRAW_OR_NC = "draw_or_nc"
METHOD_KO_TKO = "ko_tko"
METHOD_KO_TKO_DQ_SUBMISSION = "ko_tko_dq_submission"
METHOD_DRAW = "draw"

# Optic method_of_victory name suffixes after "Fighter - ".  Whitelist
# only; unrecognized suffixes are skipped (never raised) — Optic
# aggregates heterogeneous book buckets.
_OPTIC_MOV_SUFFIX: dict[str, str] = {
    "ko/tko/dq": METHOD_KO_TKO_DQ,
    "submission": METHOD_SUBMISSION,
    "decision": METHOD_DECISION,
    "ko/tko": METHOD_KO_TKO,
    "ko/tko, dq or submission": METHOD_KO_TKO_DQ_SUBMISSION,
    "draw": METHOD_DRAW,
}

# Optic method_of_ending selection / name labels → canonical key.
_OPTIC_MOF_LABEL: dict[str, str] = {
    "ko_tko_dq": METHOD_KO_TKO_DQ,
    "ko/tko/dq": METHOD_KO_TKO_DQ,
    "submission": METHOD_SUBMISSION,
    "decision": METHOD_DECISION,
    "draw": METHOD_DRAW,
}

# Novig market.type → canonical method key.  Novig does not ship one
# method-of-victory market with a bucket per outcome; it ships one Yes/No
# market PER METHOD, each carrying ``market.competitor`` (the fighter the
# Yes leg backs).  The three types below settle like-for-like with the
# Optic buckets of the same canonical key -- KO/TKO/DQ is KO/TKO/DQ on both
# sides -- so they merge onto Optic ``method_of_victory`` rows directly.
#
# Novig also lists a fight-level ``DRAW`` yes/no, which is deliberately NOT
# here: Kalshi's ``draw_or_nc`` settles draw OR no-contest and Optic's
# ``Draw`` does not, so it has no like-for-like twin (see _OPTIC_MOV_SUFFIX
# and the METHOD_DRAW / METHOD_DRAW_OR_NC split above).
_NOVIG_METHOD_TYPE: dict[str, str] = {
    "VICTORY_BY_KO_KTO_OR_DQ": METHOD_KO_TKO_DQ,
    "VICTORY_BY_SUBMISSION": METHOD_SUBMISSION,
    "VICTORY_BY_DECISION": METHOD_DECISION,
}

# Keys that have a Kalshi counterpart and should be emitted for merge.
_MERGABLE_METHODS = frozenset({
    METHOD_KO_TKO_DQ,
    METHOD_SUBMISSION,
    METHOD_DECISION,
})
# Optic rows we emit even without a Kalshi pair. Polymarket US
# ``mov-f*-ko`` is Optic ``KO/TKO`` (``ko_tko``), not Kalshi KO/TKO/DQ.
_EMITTABLE_METHODS = _MERGABLE_METHODS | {METHOD_KO_TKO}

_ROUND_KEY_RES = (
    re.compile(
        r"^(.+?)\s*::\s*(\d+)(?:st|nd|rd|th)?\s*Round$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(.+?)\s+to\s+win\s+in\s+Round\s+(\d+)$",
        re.IGNORECASE,
    ),
)

_MOV_NAME_RE = re.compile(
    r"^(.+?)\s+-\s+(.+)$",
)

# "<Fighter> to win in <not a round>" — a round-betting label whose round
# slot holds something else.  crypto.com re-lists Round of Victory in waves
# and an early wave fills that slot from PREDICT_PERIOD_TYPE, so all five of
# a fighter's legs read "… to win in Full Fight".
_ROUNDLESS_WIN_LABEL_RE = re.compile(
    r"^.+?\s+to\s+win\s+in\s+(?!round\s+\d+\b).+$",
    re.IGNORECASE,
)


def is_roundless_win_label(label: str) -> bool:
    """True when a "to win in …" label names no round to key the outcome on.

    Such a leg is unmappable: the round is the outcome identity, so a key
    built without it can neither merge with the other exchanges nor say
    which round the contract settles on.
    """
    return _ROUNDLESS_WIN_LABEL_RE.match(label.strip()) is not None


def canonicalize_fight_prop_key(label: str) -> str:
    """Normalize fight-prop outcome labels across Optic and crypto.com."""
    text = label.strip()
    for pattern in _ROUND_KEY_RES:
        match = pattern.match(text)
        if match:
            return (
                f"{normalize_player_name(match.group(1))}"
                f"_round_{int(match.group(2))}"
            )
    return normalize_player_name(text)


# Kalshi custom_strike "Method" values (typed, per market) → canonical key.
_KALSHI_METHOD_LABEL: dict[str, str] = {
    "KO/TKO/DQ": METHOD_KO_TKO_DQ,
    "Submission": METHOD_SUBMISSION,
    "Decision": METHOD_DECISION,
    "Draw/No Contest": METHOD_DRAW_OR_NC,
}


def kalshi_method_label_key(label: str | None) -> str | None:
    """Canonical method key for a Kalshi custom_strike Method, else None."""
    return _KALSHI_METHOD_LABEL.get((label or "").strip())


def novig_method_key(market_type: str) -> str | None:
    """Canonical method key for a Novig ``VICTORY_BY_*`` market type.

    Novig splits the victory method across market TYPES rather than across
    outcomes of one market, so the method comes from ``market.type`` and
    not from a selection label.  Unknown types return None, which the
    caller must treat as "drop", never as "no method".
    """
    return _NOVIG_METHOD_TYPE.get(market_type)


_VICROUND_OTHER_LABEL = "Decision / Draw / No Contest"


def kalshi_vicround_other_key(round_value: str) -> str | None:
    """round_betting key for Kalshi's non-fighter Round leg, else None.

    custom_strike Round is "1".."5" on fighter legs and this label on the
    decision / draw / no-contest leg.
    """
    if round_value.strip() != _VICROUND_OTHER_LABEL:
        return None
    return canonicalize_fight_prop_key(_VICROUND_OTHER_LABEL)


def parse_optic_mov_name(name: str) -> str | None:
    """Extract the canonical method key from an Optic method_of_victory name.

    Expected shape: ``"<Fighter> - <Method>"`` or bare ``"Draw"``.
    Returns None for unrecognized suffixes (caller skips the odd).
    """
    text = (name or "").strip()
    if not text:
        return None
    if text.lower() == "draw":
        return METHOD_DRAW
    match = _MOV_NAME_RE.match(text)
    if match is None:
        return None
    return _OPTIC_MOV_SUFFIX.get(match.group(2).strip().lower())


def parse_optic_mof_label(selection: str, name: str) -> str | None:
    """Map Optic method_of_ending selection/name to a canonical method key."""
    for raw in (selection, name):
        text = (raw or "").strip()
        if not text:
            continue
        key = _OPTIC_MOF_LABEL.get(text.lower())
        if key is not None:
            return key
        key = _OPTIC_MOF_LABEL.get(text.lower().replace(" ", "_"))
        if key is not None:
            return key
        key = _OPTIC_MOF_LABEL.get(text.lower().replace("_", "/"))
        if key is not None:
            return key
    return None


def is_mergable_method(method_key: str | None) -> bool:
    """True when the method key has a Kalshi↔Optic like-for-like pair."""
    return method_key in _MERGABLE_METHODS


def is_emittable_method(method_key: str | None) -> bool:
    """True when Optic should emit a canonical row for this method key."""
    return method_key in _EMITTABLE_METHODS


def augment_selection(selection: str, method: str) -> str:
    """Fold a canonical method key into the selection string.

    The single, byte-exact formatter shared by BOTH producers of an
    augmented selection: the mapper (``markets_us.market_mapping.selection``
    via ``BigQuery.load_mappings._optic_base``) and the OpticOdds price
    service (live fair-price selection — a vendored copy in
    ``MMOpticOdds/.../selection_normalization.py``).  Keeping the format in
    one place guarantees the trading-leg selection and the fair-price
    selection match byte-for-byte for the same contract, e.g.
    ``"Steven Asplund" + "ko_tko_dq" -> "Steven Asplund - ko_tko_dq"``.
    See docs/ufc_mov_mapping.md.
    """
    return f"{selection.strip()} - {method}"


def _normalize_mov(selection: str, name: str) -> str:
    """method_of_victory: fold the canonical method (parsed from the Optic
    ``name`` suffix) into ``selection`` so otherwise-identical fighter
    contracts (``Fighter - Decision`` vs ``Fighter - KO/TKO/DQ``) stop
    colliding.

    Fail-safe: a non-emittable or unparseable bucket keeps the raw selection
    unchanged — Draw / composite Optic buckets stay unmapped.
    """
    method = parse_optic_mov_name(name)
    if method is None or not is_emittable_method(method):
        return selection
    return augment_selection(selection, method)


# (sport, market_id) -> callable(selection, name) -> augmented selection.
# Sport-scoped because a raw Optic market_id can mean different things across
# sports.  No-op for any (sport, market_id) not listed here — this registry is
# the single place that declares which markets need name-based disambiguation.
_SELECTION_NORMALIZERS = {
    ("mma", "method_of_victory"): _normalize_mov,
}


def normalize_selection(
    sport: str | None,
    market_id: str | None,
    selection: str,
    name: str,
) -> str:
    """Sport-aware selection normalizer (single entry point).

    Returns ``selection`` unchanged unless ``(sport, market_id)`` is a
    registered name-only-discriminator market (currently just MMA
    ``method_of_victory``).
    """
    if sport is None or market_id is None:
        return selection
    fn = _SELECTION_NORMALIZERS.get((sport, market_id))
    if fn is None:
        return selection
    return fn(selection, name)
