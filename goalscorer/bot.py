"""Slack Socket Mode listener for #goalscorer-alerts.

Handles review-card buttons (Accept / pick / Other… / Dismiss) and channel
commands (see ``goalscorer.commands``). Socket Mode opens an outbound websocket,
so the pod needs no ingress. Needs SLACK_BOT_TOKEN (xoxb) and SLACK_APP_TOKEN
(xapp, connections:write).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from goalscorer import cards
from goalscorer.channel import handle_command
from goalscorer.commands import parse_command
from goalscorer.context import Context
from goalscorer.models import ReviewItem
from goalscorer.review import record, resolve_typed

logger = logging.getLogger(__name__)

Chooser = Callable[[dict[str, Any], ReviewItem], str | None]


def _allowed(ctx: Context, user: str) -> bool:
    """True when no approver list is set or the user is on it."""
    return not ctx.settings.approver_ids or user in ctx.settings.approver_ids


def _finish(client: WebClient, where: tuple[str, str], item: ReviewItem, note: str) -> None:
    """Replace the card's buttons with the outcome."""
    channel, ts = where
    client.chat_update(
        channel=channel, ts=ts, text=f"{item.player_code}: {note}", blocks=cards.resolved_card(item, note)
    )


def _record_and_finish(
    ctx: Context, client: WebClient, where: tuple[str, str], item: ReviewItem, selection: str, user: str
) -> None:
    """Record the mapping, then close the card; on failure tell only the clicker."""
    try:
        note = record(ctx, item, selection, user)
    except Exception:
        logger.exception("recording %s → %s failed", item.ticker, selection)
        client.chat_postEphemeral(channel=where[0], user=user, text=f"Couldn't record `{item.ticker}` — see bot logs.")
        return
    _finish(client, where, item, note)


def _card_click(ctx: Context, choose: Chooser):
    """Listener for a card button/select: resolve the item, then record the chosen name."""

    def listener(ack, body: dict[str, Any], client: WebClient) -> None:
        ack()
        user = body["user"]["id"]
        where = (body["channel"]["id"], body["message"]["ts"])
        if not _allowed(ctx, user):
            client.chat_postEphemeral(channel=where[0], user=user, text="You're not on the goalscorer approver list.")
            return
        item = cards.item_from_message(body["message"])
        selection = choose(body, item) if item else None
        if item and selection:
            _record_and_finish(ctx, client, where, item, selection, user)

    return listener


def _accepted(_body: dict[str, Any], item: ReviewItem) -> str | None:
    """Accept button → the suggested name."""
    return item.suggested


def _picked(body: dict[str, Any], _item: ReviewItem) -> str | None:
    """Picker → the chosen option's value."""
    return body["actions"][0]["selected_option"]["value"]


def _on_dismiss(ctx: Context):
    """Listener that closes a card without recording anything."""

    def listener(ack, body: dict[str, Any], client: WebClient) -> None:
        ack()
        user = body["user"]["id"]
        item = cards.item_from_message(body["message"])
        if item and _allowed(ctx, user):
            where = (body["channel"]["id"], body["message"]["ts"])
            _finish(client, where, item, f":no_entry_sign: Dismissed by <@{user}>")

    return listener


def _on_other(ack, body: dict[str, Any], client: WebClient) -> None:
    """Open the Other… modal for a card."""
    ack()
    item = cards.item_from_message(body["message"])
    if item is None:
        return
    names = cards.names_from_message(body["message"])
    view = cards.other_modal(item, body["channel"]["id"], body["message"]["ts"], names)
    client.views_open(trigger_id=body["trigger_id"], view=view)


def _on_other_submit(ctx: Context):
    """Listener for the Other… modal: validate inline, then record."""

    def listener(ack, body: dict[str, Any], view: dict[str, Any], client: WebClient) -> None:
        sub = cards.parse_other_submission(view)
        user = body["user"]["id"]
        if not _allowed(ctx, user):
            ack(response_action="errors", errors={"selection": "You're not on the goalscorer approver list."})
            return
        selection, error = resolve_typed(sub.typed, sub.names, sub.force)
        if error or not selection:
            ack(response_action="errors", errors={"selection": error or "Enter a selection name."})
            return
        ack()
        _record_and_finish(ctx, client, (sub.channel, sub.ts), sub.item, selection, user)

    return listener


def _on_message(ctx: Context):
    """Listener for top-level channel messages that parse as commands."""

    def listener(event: dict[str, Any], client: WebClient) -> None:
        if event.get("channel") != ctx.settings.slack_channel_id:
            return
        if event.get("subtype") or event.get("bot_id") or event.get("thread_ts"):
            return
        command = parse_command(event.get("text", ""))
        if command is None:
            return
        user = event.get("user", "")

        def reply(text: str) -> None:
            client.chat_postMessage(channel=event["channel"], thread_ts=event["ts"], text=text)

        if not _allowed(ctx, user):
            reply("You're not on the goalscorer approver list.")
            return
        try:
            replies = handle_command(ctx, command, user)
        except Exception as exc:
            logger.exception("command %s failed", command)
            replies = [f":x: `{command.value}` failed: {exc}"]
        for text in replies:
            reply(text)

    return listener


def build_app(ctx: Context) -> App:
    """Bolt app with every listener registered."""
    app = App(token=ctx.settings.slack_bot_token)
    app.action(cards.ACTION_ACCEPT)(_card_click(ctx, _accepted))
    app.action(cards.ACTION_PICK)(_card_click(ctx, _picked))
    app.action(cards.ACTION_DISMISS)(_on_dismiss(ctx))
    app.action(cards.ACTION_OTHER)(_on_other)
    app.view(cards.VIEW_OTHER)(_on_other_submit(ctx))
    app.event("message")(_on_message(ctx))
    return app


def join_channel(client: WebClient, channel: str) -> None:
    """Join the (public) channel so nobody has to invite the bot; private channels still need an invite."""
    try:
        client.conversations_join(channel=channel)
    except SlackApiError as exc:
        logger.warning(
            "could not join %s (%s) — invite the bot if the channel is private", channel, exc.response.get("error")
        )


def run_bot(ctx: Context) -> None:
    """Connect over Socket Mode and serve until the process is stopped."""
    if not (ctx.settings.slack_bot_token and ctx.settings.slack_app_token and ctx.settings.slack_channel_id):
        raise RuntimeError("bot needs SLACK_BOT_TOKEN, SLACK_APP_TOKEN and GOALSCORER_SLACK_CHANNEL_ID")
    app = build_app(ctx)
    join_channel(app.client, ctx.settings.slack_channel_id)
    logger.info("goalscorer bot connecting (channel %s)", ctx.settings.slack_channel_id)
    SocketModeHandler(app, ctx.settings.slack_app_token).start()
