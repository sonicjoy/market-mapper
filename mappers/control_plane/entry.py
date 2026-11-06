"""Trader-facing paste parse + verify for M3b manual entry.

Traders paste a symbol or id; this module detects sportsbook, matches a
league parser, extracts codes, and returns a human ExtractionPreview. Internal
ids stay server-side — the preview token is an HMAC of the extraction so submit
does not require the client to send rule_set_id or canonical_key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Protocol

from mappers.control_plane.alias_ok import signed_alias_ok
from mappers.control_plane.dry_run import resolve_alias
from mappers.control_plane.live_evidence import apply_evidence_fn
from mappers.control_plane.preview_token import sign_preview, unsign_preview
from mappers.control_plane.store import EntityRow

# Re-export for callers that import from entry.
__all__ = ["sign_preview", "unsign_preview", "league_label", "verify_entry"]

# Null preview fields — bandit B105 false-positive on names containing "token".
_ABSENT: str | None = None  # nosec B105
ACK_RULES_WRITE = (
    "Acknowledge this writes the mapping-rules snapshot and can activate live mapping in this environment."
)
_CRYPTO_ID_RE = re.compile(r"^\d{6,}$")
_LEAGUE_LABELS: dict[str, str] = {}


def league_label(league_key: str) -> str:
    """Human label for a league key (cached from the tip when available)."""
    if league_key in _LEAGUE_LABELS:
        return _LEAGUE_LABELS[league_key]
    return league_key.replace("_", " ").title()


def _register_league_labels(store: Any | None = None) -> None:
    """Load display labels from the activated tip once."""
    if store is None:
        return
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return
    for row in store.leagues_for(rid):
        slug = row.league
        if slug not in _LEAGUE_LABELS:
            _LEAGUE_LABELS[slug] = slug.replace("_", " ").title()


class LiveLookup(Protocol):
    """Soft live evidence: True if paste was seen recently on the exchange."""

    def seen(self, paste: str, *, sportsbook: str | None) -> bool: ...


class NullLiveLookup:
    """Default: no live hit → warning (never a hard block)."""

    def seen(self, paste: str, *, sportsbook: str | None) -> bool:
        """Always miss."""
        return False


@dataclass(frozen=True)
class ParsedPaste:
    """Deterministic extraction from a trader paste."""

    sportsbook: str
    league: str
    alias_value: str
    alias_kind: str
    entity_type: str
    partner_codes: tuple[str, ...]
    raw_paste: str


def detect_sportsbook(paste: str) -> str | None:
    """Infer sportsbook from paste shape.

    A short all-digit value (under 6 digits) is not guessed: Optic competitor ids are 12+ hex
    characters, and short numbers are other feeds' ids (a TxODDS TeamId such as 1622 would
    otherwise be drafted as an Optic pin, which classify reads). Pin those from the structured form.
    """
    text = paste.strip()
    if _CRYPTO_ID_RE.match(text):
        return "crypto.com"
    if len(text) >= 8 and text.replace("-", "").isalnum():
        return "optic"
    return None


def parse_paste(
    paste: str,
    entities: list[EntityRow],
    *,
    store: Any | None = None,
) -> ParsedPaste | None:
    """Parse trader paste into sportsbook/league/alias or None (format fail)."""
    text = paste.strip()
    if not text:
        return None
    book = detect_sportsbook(text)
    if book == "crypto.com":
        return ParsedPaste(
            sportsbook="crypto.com",
            league="",
            alias_value=text,
            alias_kind="external_id",
            entity_type="team",
            partner_codes=(),
            raw_paste=text,
        )
    if book == "optic":
        return ParsedPaste(
            sportsbook="optic",
            league="",
            alias_value=text,
            alias_kind="external_id",
            entity_type="team",
            partner_codes=(),
            raw_paste=text,
        )
    return None


def _canonical_for(
    entities: list[EntityRow],
    *,
    league: str,
    sportsbook: str,
    alias_kind: str,
    alias_value: str,
    provided_name: str | None,
) -> tuple[str, str | None, list[dict[str, str]]]:
    """Resolve canonical key/name and optional disambiguation choices."""
    claimants = resolve_alias(
        entities,
        league=league,
        sportsbook=sportsbook,
        alias_kind=alias_kind,
        alias_value=alias_value,
    )
    if len(claimants) == 1:
        key = claimants[0]
        name = next(
            (e.canonical_name for e in entities if e.league == league and e.canonical_key == key),
            provided_name,
        )
        return key, name, []
    if len(claimants) > 1:
        choices = []
        for key in claimants:
            ent = next(e for e in entities if e.league == league and e.canonical_key == key)
            choices.append(
                {
                    "label": ent.canonical_name or key,
                    "canonical_key": key,
                }
            )
        if provided_name:
            choices.append({"label": f"New: {provided_name}", "canonical_key": alias_value})
        return alias_value, provided_name, choices
    return alias_value, provided_name, []


def _apply_disambiguation(
    choices: list[dict[str, str]],
    disambiguation_label: str | None,
    canonical_key: str,
    canonical_name: str | None,
) -> tuple[str, str | None, list[str]]:
    """Resolve disambiguation choice; return key, name, blockers."""
    if not choices:
        return canonical_key, canonical_name, []
    if not disambiguation_label:
        return canonical_key, canonical_name, [
            "This code matches more than one entity. Pick which one to pin."
        ]
    picked = next((c for c in choices if c["label"] == disambiguation_label), None)
    if picked is None:
        return canonical_key, canonical_name, ["That disambiguation choice is not valid."]
    return picked["canonical_key"], picked["label"].removeprefix("New: ").strip(), []


def _preview_card(
    *,
    parsed: ParsedPaste,
    canonical_key: str,
    canonical_name: str,
    note: str | None,
    disambiguation_label: str | None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Build trader preview + signed extraction token."""
    book_label = {"crypto.com": "crypto.com", "optic": "Optic"}.get(
        parsed.sportsbook, parsed.sportsbook
    )
    ll = league_label(parsed.league)
    summary = (
        f"Pin {book_label} {parsed.alias_kind} `{parsed.alias_value}` to "
        f"**{canonical_name}** in **{ll}**"
    )
    return signed_alias_ok(
        sportsbook=parsed.sportsbook,
        league=parsed.league,
        league_label_text=ll,
        alias_kind=parsed.alias_kind,
        alias_value=parsed.alias_value,
        entity_type=parsed.entity_type,
        canonical_key=canonical_key,
        canonical_name=canonical_name,
        raw_paste=parsed.raw_paste,
        note=note,
        summary=summary,
        warnings=[],
        reassign=False,
        disambiguation_label=disambiguation_label,
        evidence_refs=list(evidence_refs or []),
    )


def _parse_or_block(
    paste: str,
    entities: list[EntityRow],
    *,
    league: str | None = None,
    store: Any | None = None,
) -> tuple[ParsedPaste | None, dict[str, Any] | None]:
    """Parse paste; return (parsed, None) or (None, blocked_response)."""
    parsed = parse_paste(paste, entities, store=store)
    if parsed is None:
        return None, {
            "ok": False,
            "blockers": ["Could not parse that paste. Check the symbol or id."],
            "warnings": [],
            "preview": _ABSENT,
            "preview_token": _ABSENT,
            "needs_name": False,
            "needs_live_ack": False,
            "needs_league": False,
            "disambiguation_choices": [],
        }
    chosen = (league or "").strip()
    if not parsed.league and chosen:
        parsed = replace(parsed, league=chosen)
    if not parsed.league:
        return None, _blocked(
            ["Could not tell which league this belongs to. Select a league."],
            [],
            needs_league=True,
        )
    return parsed, None


def verify_entry(
    *,
    paste: str,
    provided_name: str | None,
    note: str | None,
    acknowledge_live_warning: bool,
    disambiguation_label: str | None,
    entities: list[EntityRow],
    live: LiveLookup | None = None,
    league: str | None = None,
    store: Any = None,
    evidence_fn: Any = None,
) -> dict[str, Any]:
    """Run format + live + rules gates; return trader-safe ExtractionPreview."""
    _register_league_labels(store)
    live = live or NullLiveLookup()
    parsed, blocked = _parse_or_block(paste, entities, league=league, store=store)
    if blocked is not None or parsed is None:
        return blocked or _blocked(["Could not parse that paste."], [])
    warnings: list[str] = []
    if evidence_fn is None and not live.seen(parsed.raw_paste, sportsbook=parsed.sportsbook):
        warnings.append("Not seen recently on the exchange. Confirm you pasted the right id.")
    return _verify_rules_and_preview(
        parsed=parsed,
        provided_name=provided_name,
        note=note,
        acknowledge_live_warning=acknowledge_live_warning,
        disambiguation_label=disambiguation_label,
        entities=entities,
        warnings=warnings,
        store=store,
        evidence_fn=evidence_fn,
    )


def _needs_name_response(warnings: list[str]) -> dict[str, Any]:
    """Blocked response when canonical name is missing."""
    return {
        "ok": False,
        "blockers": ["Who is this? Enter the team, player, or fighter name."],
        "warnings": warnings,
        "preview": _ABSENT,
        "preview_token": _ABSENT,
        "needs_name": True,
        "needs_live_ack": bool(warnings),
        "needs_league": False,
        "disambiguation_choices": [],
    }


def _choice_response(
    blockers: list[str],
    warnings: list[str],
    choices: list[dict[str, str]],
) -> dict[str, Any]:
    """Blocked response listing disambiguation labels."""
    return {
        "ok": False,
        "blockers": blockers,
        "warnings": warnings,
        "preview": _ABSENT,
        "preview_token": _ABSENT,
        "needs_name": False,
        "needs_live_ack": bool(warnings),
        "needs_league": False,
        "disambiguation_choices": [{"label": c["label"]} for c in choices],
    }


def _verify_rules_and_preview(
    *,
    parsed: ParsedPaste,
    provided_name: str | None,
    note: str | None,
    acknowledge_live_warning: bool,
    disambiguation_label: str | None,
    entities: list[EntityRow],
    warnings: list[str],
    store: Any = None,
    evidence_fn: Any = None,
) -> dict[str, Any]:
    """Rules gate + preview assembly after format/live checks."""
    canonical_key, canonical_name, choices = _canonical_for(
        entities,
        league=parsed.league,
        sportsbook=parsed.sportsbook,
        alias_kind=parsed.alias_kind,
        alias_value=parsed.alias_value,
        provided_name=(provided_name or "").strip() or None,
    )
    canonical_key, canonical_name, blockers = _apply_disambiguation(
        choices, disambiguation_label, canonical_key, canonical_name
    )
    if blockers and choices and not disambiguation_label:
        return _choice_response(blockers, warnings, choices)
    if blockers:
        return _blocked(blockers, warnings)
    if not canonical_name:
        return _needs_name_response(warnings)
    refs, live_block = apply_evidence_fn(
        evidence_fn, store, league=parsed.league, sportsbook=parsed.sportsbook,
        alias_kind=parsed.alias_kind, alias_value=parsed.alias_value,
        canonical_name=canonical_name, raw_paste=parsed.raw_paste)
    if live_block:
        return _blocked(live_block, warnings)
    if evidence_fn is None and warnings and not acknowledge_live_warning:
        return _blocked(["Acknowledge the live-evidence warning to continue."], warnings)
    card = _preview_card(
        parsed=parsed, canonical_key=canonical_key, canonical_name=canonical_name,
        note=note, disambiguation_label=disambiguation_label, evidence_refs=refs)
    card["warnings"] = warnings
    return card


def _blocked(
    blockers: list[str],
    warnings: list[str],
    *,
    needs_league: bool = False,
) -> dict[str, Any]:
    """Standard blocked verify response."""
    return {
        "ok": False,
        "blockers": blockers,
        "warnings": warnings,
        "preview": _ABSENT,
        "preview_token": _ABSENT,
        "needs_name": False,
        "needs_live_ack": bool(warnings),
        "needs_league": needs_league,
        "disambiguation_choices": [],
    }
