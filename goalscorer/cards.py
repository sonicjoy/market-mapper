"""Block Kit review cards and the "Other…" modal.

Each card carries its review item as compact JSON in every button's value, so
the bot needs no state of its own: a click decodes the item from the message,
records the mapping, and rewrites the card without its buttons.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from goalscorer.models import ReviewItem

ACTION_ACCEPT = "gs_accept"
ACTION_PICK = "gs_pick"
ACTION_OTHER = "gs_other"
ACTION_DISMISS = "gs_dismiss"
VIEW_OTHER = "gs_other_submit"
BLOCK_REVIEW = "gs_review"
_FORCE = "force"

# Slack limits: button/option text 75 chars, option value 150, 100 options per group.
_TEXT_MAX = 75
_VALUE_MAX = 150
_ALL_PLAYERS_MAX = 90
_METADATA_MAX = 3000


def _text(value: str) -> dict:
    """plain_text object clipped to Slack's 75-char limit."""
    return {"type": "plain_text", "text": value[:_TEXT_MAX], "emoji": True}


def _mrkdwn(value: str) -> dict:
    """mrkdwn text object."""
    return {"type": "mrkdwn", "text": value}


def encode_item(item: ReviewItem) -> str:
    """Compact JSON for a button value (Slack caps it at 2000 chars)."""
    payload = {
        "g": item.game_id,
        "d": item.start_date.isoformat(),
        "sp": item.sport,
        "lg": item.league,
        "gl": item.game_label[:_VALUE_MAX],
        "pc": item.player_code,
        "t": item.ticker,
        "s": item.suggested,
    }
    return json.dumps(payload, separators=(",", ":"))


def decode_item(value: str) -> ReviewItem:
    """Inverse of encode_item (ranked/candidates are not carried)."""
    p = json.loads(value)
    return ReviewItem(
        game_id=p["g"],
        start_date=datetime.fromisoformat(p["d"]),
        sport=p["sp"],
        league=p["lg"],
        game_label=p["gl"],
        player_code=p["pc"],
        ticker=p["t"],
        suggested=p.get("s"),
    )


def _summary(item: ReviewItem) -> dict:
    """The card's description section."""
    headline = f"*Unmapped player* `{item.base_code}` (1+ / 2+ / 3+ / first goal)" + (
        "" if item.suggested else " — no confident match"
    )
    lines = [
        headline,
        f"*Game:* {item.game_label} ({item.league}, {item.start_date:%d %b %Y})",
        f"*Ticker:* `{item.ticker}`",
    ]
    if item.suggested:
        lines.append(f"*Suggested:* _{item.suggested}_")
    return {"type": "section", "text": _mrkdwn("\n".join(lines))}


def _option(value: str, label: str | None = None) -> dict:
    """static_select / checkbox option."""
    return {"text": _text(label or value), "value": value}


def _picker(item: ReviewItem) -> dict | None:
    """Player picker: best matches first, then everyone else in the game."""
    ranked_names = [name for name, _ in item.ranked if len(name) <= _VALUE_MAX]
    rest = [c for c in item.candidates if c not in ranked_names and len(c) <= _VALUE_MAX]
    groups = []
    if ranked_names:
        scores = dict(item.ranked)
        options = [_option(n, f"{n} ({scores[n]}%)") for n in ranked_names]
        groups.append({"label": _text("Best matches"), "options": options})
    if rest:
        options = [_option(n) for n in rest[:_ALL_PLAYERS_MAX]]
        groups.append({"label": _text("All players in this game"), "options": options})
    if not groups:
        return None
    return {
        "type": "static_select",
        "action_id": ACTION_PICK,
        "placeholder": _text("Pick a player"),
        "option_groups": groups,
    }


def review_card(item: ReviewItem) -> list[dict]:
    """Card with Accept (when suggested), a player picker, Other… and Dismiss."""
    value = encode_item(item)
    elements: list[dict] = []
    if item.suggested:
        elements.append(
            {
                "type": "button",
                "action_id": ACTION_ACCEPT,
                "style": "primary",
                "text": _text(f"Accept: {item.suggested}"),
                "value": value,
            }
        )
    picker = _picker(item)
    if picker:
        elements.append(picker)
    elements.append({"type": "button", "action_id": ACTION_OTHER, "text": _text("Other…"), "value": value})
    elements.append({"type": "button", "action_id": ACTION_DISMISS, "text": _text("Dismiss"), "value": value})
    blocks = [_summary(item)]
    if item.ranked:
        best = " · ".join(f"{n} ({s}%)" for n, s in item.ranked[:3])
        blocks.append({"type": "context", "elements": [_mrkdwn(f"Best matches: {best}")]})
    blocks.append({"type": "actions", "block_id": BLOCK_REVIEW, "elements": elements})
    return blocks


def resolved_card(item: ReviewItem, note: str) -> list[dict]:
    """The card after a decision: same summary, buttons replaced by the outcome."""
    return [_summary(item), {"type": "context", "elements": [_mrkdwn(note)]}]


def _review_elements(message: dict[str, Any]) -> list[dict]:
    """The card's actions-block elements, or [] once resolved."""
    for block in message.get("blocks", []):
        if block.get("block_id") == BLOCK_REVIEW:
            return block.get("elements", [])
    return []


def item_from_message(message: dict[str, Any]) -> ReviewItem | None:
    """Decode the review item carried by a card's buttons."""
    for element in _review_elements(message):
        if element.get("type") == "button" and element.get("value"):
            return decode_item(element["value"])
    return None


def names_from_message(message: dict[str, Any]) -> list[str]:
    """Every selection name offered in a card's picker."""
    names: list[str] = []
    for element in _review_elements(message):
        for group in element.get("option_groups", []):
            names.extend(opt["value"] for opt in group.get("options", []))
    return names


def _modal_metadata(item: ReviewItem, channel: str, ts: str, names: list[str]) -> str:
    """private_metadata JSON, dropping trailing names to stay under Slack's 3000 chars."""
    names = list(names)
    while True:
        meta = {"item": encode_item(item), "channel": channel, "ts": ts, "names": names}
        encoded = json.dumps(meta, separators=(",", ":"))
        if len(encoded) <= _METADATA_MAX or not names:
            return encoded
        names.pop()


def other_modal(item: ReviewItem, channel: str, ts: str, names: list[str]) -> dict:
    """Modal to type a selection name; carries the card location and its candidate names."""
    meta = _modal_metadata(item, channel, ts, names)
    name_input: dict = {"type": "plain_text_input", "action_id": "value"}
    if item.suggested:
        name_input["initial_value"] = item.suggested
    force = {
        "type": "checkboxes",
        "action_id": "value",
        "options": [_option(_FORCE, "Use exactly as typed (no book lists this name)")],
    }
    return {
        "type": "modal",
        "callback_id": VIEW_OTHER,
        "title": _text("Map goal ticker"),
        "submit": _text("Map"),
        "close": _text("Cancel"),
        "private_metadata": meta,
        "blocks": [
            {"type": "section", "text": _mrkdwn(f"`{item.ticker}`\n{item.game_label}")},
            {"type": "input", "block_id": "selection", "label": _text("Selection name"), "element": name_input},
            {"type": "input", "block_id": _FORCE, "optional": True, "label": _text("Spelling"), "element": force},
        ],
    }


@dataclass(frozen=True)
class OtherSubmission:
    """A submitted Other… modal."""

    item: ReviewItem
    channel: str
    ts: str
    names: list[str]
    typed: str
    force: bool


def parse_other_submission(view: dict[str, Any]) -> OtherSubmission:
    """Decode the modal's metadata and inputs."""
    meta = json.loads(view["private_metadata"])
    values = view["state"]["values"]
    typed = (values["selection"]["value"].get("value") or "").strip()
    force = bool(values.get(_FORCE, {}).get("value", {}).get("selected_options"))
    return OtherSubmission(decode_item(meta["item"]), meta["channel"], meta["ts"], meta["names"], typed, force)
