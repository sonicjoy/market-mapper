"""Review card / modal payloads and decoding."""

import json

from goalscorer import cards
from goalscorer.models import ReviewItem
from tests.goalscorer.fakes import KICKOFF


def _item(**kw) -> ReviewItem:
    base = {
        "game_id": "g1",
        "start_date": KICKOFF,
        "sport": "soccer",
        "league": "England - Premier League",
        "game_label": "Arsenal vs Chelsea",
        "player_code": "ARSMMERIN1-1",
        "ticker": "KXEPLGOAL-26SEP26ARSCHE-ARSMMERIN1-1",
        "suggested": "Mikel Merino",
        "ranked": [("Mikel Merino", 100), ("Martin Odegaard", 10)],
        "candidates": ["Bukayo Saka", "Martin Odegaard", "Mikel Merino"],
    }
    base.update(kw)
    return ReviewItem(**base)


def _actions(blocks):
    return next(b for b in blocks if b.get("block_id") == cards.BLOCK_REVIEW)["elements"]


def test_item_round_trips_through_button_value():
    item = _item()
    decoded = cards.decode_item(cards.encode_item(item))
    assert (decoded.game_id, decoded.ticker, decoded.suggested, decoded.start_date) == (
        item.game_id,
        item.ticker,
        item.suggested,
        item.start_date,
    )
    assert len(cards.encode_item(item)) < 2000


def test_card_offers_accept_picker_other_dismiss():
    elements = _actions(cards.review_card(_item()))
    assert [e.get("action_id") for e in elements] == [
        cards.ACTION_ACCEPT,
        cards.ACTION_PICK,
        cards.ACTION_OTHER,
        cards.ACTION_DISMISS,
    ]
    groups = elements[1]["option_groups"]
    assert [o["value"] for o in groups[0]["options"]] == ["Mikel Merino", "Martin Odegaard"]
    assert [o["value"] for o in groups[1]["options"]] == ["Bukayo Saka"]


def test_unmatched_card_has_no_accept():
    elements = _actions(cards.review_card(_item(suggested=None, ranked=[], candidates=[])))
    assert [e.get("action_id") for e in elements] == [cards.ACTION_OTHER, cards.ACTION_DISMISS]


def test_decoding_from_posted_message():
    message = {"blocks": cards.review_card(_item())}
    item = cards.item_from_message(message)
    assert item and item.ticker == _item().ticker
    assert cards.names_from_message(message) == ["Mikel Merino", "Martin Odegaard", "Bukayo Saka"]
    resolved = {"blocks": cards.resolved_card(_item(), "done")}
    assert cards.item_from_message(resolved) is None


def test_modal_metadata_stays_under_slack_limit():
    names = [f"Player Number {i:03d} With A Long Name" for i in range(200)]
    view = cards.other_modal(_item(), "C1", "123.4", names)
    assert len(view["private_metadata"]) <= 3000
    assert json.loads(view["private_metadata"])["names"] == names[: len(json.loads(view["private_metadata"])["names"])]


def test_parse_other_submission():
    view = cards.other_modal(_item(), "C1", "123.4", ["Mikel Merino"])
    view["state"] = {
        "values": {
            "selection": {"value": {"value": " mikel merino "}},
            "force": {"value": {"selected_options": [{"value": "force"}]}},
        }
    }
    sub = cards.parse_other_submission(view)
    assert (sub.channel, sub.ts, sub.typed, sub.force, sub.names) == (
        "C1",
        "123.4",
        "mikel merino",
        True,
        ["Mikel Merino"],
    )
    assert sub.item.ticker == _item().ticker
