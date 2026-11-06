"""Bot listeners, driven with recorded Slack payloads and a fake WebClient."""

from unittest.mock import MagicMock

from goalscorer import bot, cards
from goalscorer.models import ReviewItem
from tests.goalscorer.fakes import KICKOFF, make_ctx

ITEM = ReviewItem(
    "g1",
    KICKOFF,
    "soccer",
    "England - Premier League",
    "Arsenal vs Chelsea",
    "ARSMMERIN1-1",
    "KXEPLGOAL-26SEP26ARSCHE-ARSMMERIN1-1",
    suggested="Mikel Merino",
    ranked=[("Mikel Merino", 90)],
    candidates=["Bukayo Saka", "Mikel Merino"],
)


def _body(user="U1", **extra):
    body = {
        "user": {"id": user},
        "channel": {"id": "C1"},
        "message": {"ts": "111.1", "blocks": cards.review_card(ITEM)},
        "trigger_id": "trig",
    }
    body.update(extra)
    return body


def test_accept_records_and_rewrites_card():
    ctx, client, ack = make_ctx(), MagicMock(), MagicMock()
    bot._card_click(ctx, bot._accepted)(ack, _body(), client)
    ack.assert_called_once()
    assert ctx.store.inserted[0].selection == "Mikel Merino"  # type: ignore[attr-defined]
    kwargs = client.chat_update.call_args.kwargs
    assert kwargs["ts"] == "111.1"
    assert all(b.get("block_id") != cards.BLOCK_REVIEW for b in kwargs["blocks"])


def test_pick_uses_selected_option():
    ctx, client = make_ctx(), MagicMock()
    body = _body(actions=[{"selected_option": {"value": "Bukayo Saka"}}])
    bot._card_click(ctx, bot._picked)(MagicMock(), body, client)
    assert ctx.store.inserted[0].selection == "Bukayo Saka"  # type: ignore[attr-defined]


def test_non_approver_gets_ephemeral_refusal():
    ctx, client = make_ctx(approver_ids=frozenset({"U9"})), MagicMock()
    bot._card_click(ctx, bot._accepted)(MagicMock(), _body(user="U1"), client)
    client.chat_postEphemeral.assert_called_once()
    assert ctx.store.inserted == []  # type: ignore[attr-defined]


def test_other_opens_modal_with_card_names():
    client = MagicMock()
    bot._on_other(MagicMock(), _body(), client)
    view = client.views_open.call_args.kwargs["view"]
    assert view["callback_id"] == cards.VIEW_OTHER
    assert '"names":["Mikel Merino","Bukayo Saka"]' in view["private_metadata"]


def test_other_submit_rejects_unknown_name_inline():
    ctx, client, ack = make_ctx(), MagicMock(), MagicMock()
    view = cards.other_modal(ITEM, "C1", "111.1", ["Mikel Merino"])
    view["state"] = {"values": {"selection": {"value": {"value": "Mikel Merinoo"}}, "force": {"value": {}}}}
    bot._on_other_submit(ctx)(ack, {"user": {"id": "U1"}}, view, client)
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert ctx.store.inserted == []  # type: ignore[attr-defined]


def test_channel_message_runs_command_in_thread(monkeypatch):
    ctx, client = make_ctx(), MagicMock()
    monkeypatch.setattr(bot, "handle_command", lambda ctx, command, user: [f"ran {command.value}"])
    listener = bot._on_message(ctx)
    listener({"channel": "C1", "ts": "5.5", "user": "U1", "text": "202608110FBC008C"}, client)
    client.chat_postMessage.assert_called_once_with(channel="C1", thread_ts="5.5", text="ran 202608110FBC008C")
    for ignored in (
        {"channel": "C1", "ts": "6", "user": "U1", "text": "hello"},
        {"channel": "C2", "ts": "7", "user": "U1", "text": "202608110FBC008C"},
        {"channel": "C1", "ts": "8", "bot_id": "B1", "text": "202608110FBC008C"},
        {"channel": "C1", "ts": "9", "thread_ts": "5.5", "user": "U1", "text": "202608110FBC008C"},
    ):
        listener(ignored, client)
    assert client.chat_postMessage.call_count == 1


def test_join_channel_tolerates_private_channel():
    from slack_sdk.errors import SlackApiError

    client = MagicMock()
    client.conversations_join.side_effect = SlackApiError("no", {"error": "method_not_supported_for_channel_type"})
    bot.join_channel(client, "C1")  # logs, does not raise
    client.conversations_join.assert_called_once_with(channel="C1")
