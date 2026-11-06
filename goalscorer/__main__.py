"""Goalscorer mapper CLI.

    python -m goalscorer pregame   [--date YYYY-MM-DD]   map upcoming fixtures (CronJob)
    python -m goalscorer listing                         move guesses onto Kalshi's listed tickers (CronJob)
    python -m goalscorer reconcile [--date D] [--team T] learn codes from played games (CronJob)
    python -m goalscorer pnl       [--date D]            PnL PDF to Slack (CronJob)
    python -m goalscorer bot                             Slack Socket Mode listener (Deployment)
    python -m goalscorer map <fixture id | game_id | Kalshi ticker>
    python -m goalscorer add-league <optic slug> [KX…GOAL]

reconcile and pnl default to yesterday (UTC); pregame to today. Scheduled
commands exit 0 without doing anything when GOALSCORER_MAPPER_ENABLED=0.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from goalscorer.context import Context
from goalscorer.timeutil import utcnow

logger = logging.getLogger("goalscorer")

_SCHEDULED = {"pregame", "listing", "reconcile", "pnl"}


def _parser() -> argparse.ArgumentParser:
    """Subcommands and their flags."""
    parser = argparse.ArgumentParser(prog="goalscorer", description="Kalshi goalscorer mapper")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("pregame", "reconcile", "pnl"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--date", type=date.fromisoformat, default=None)
        if name == "reconcile":
            cmd.add_argument("--team", default=None, help="only fixtures whose teams contain this text")
    sub.add_parser("listing")
    sub.add_parser("bot")
    map_cmd = sub.add_parser("map")
    map_cmd.add_argument("ref")
    league_cmd = sub.add_parser("add-league")
    league_cmd.add_argument("slug")
    league_cmd.add_argument("goal_prefix", nargs="?", default=None)
    return parser


def _pregame(ctx: Context, day: date) -> None:
    """Scheduled pre-game run; posts a summary only when something was published."""
    from goalscorer.pregame import run_pregame, summary_text

    outcomes = run_pregame(ctx, day)
    if any(o.planned for o in outcomes):
        ctx.slack.post(summary_text(f"Pre-game mappings — {day}", outcomes, ctx.settings.dry_run))


def _one_off(ctx: Context, args: argparse.Namespace) -> None:
    """`map` / `add-league` from the CLI, printing the replies the bot would post."""
    from goalscorer.channel import handle_command
    from goalscorer.commands import Command, parse_command

    if args.command == "map":
        command = parse_command(args.ref)
        if command is None or command.kind == "add_league":
            raise SystemExit(f"not a fixture id, game_id or Kalshi ticker: {args.ref}")
    else:
        command = Command("add_league", args.slug, args.goal_prefix)
    for reply in handle_command(ctx, command, user="cli"):
        print(reply)


def _run(ctx: Context, args: argparse.Namespace) -> None:
    """Dispatch one parsed command."""
    today = utcnow().date()
    yesterday = today - timedelta(days=1)
    if args.command == "pregame":
        _pregame(ctx, args.date or today)
    elif args.command == "listing":
        from goalscorer.listing import run_listing_check

        moves = run_listing_check(ctx)
        logger.info("listing check: %d override(s) moved", len(moves))
    elif args.command == "reconcile":
        from goalscorer.reconcile import run_reconcile

        report = run_reconcile(ctx, args.date or yesterday, team=args.team)
        logger.info(
            "reconcile %s: %d fixtures, %d auto (%d recorded), %d for review; %d 2+/3+ and %d first goal rows recorded",
            report.day,
            report.fixtures,
            len(report.auto),
            report.recorded,
            len(report.review),
            report.lines_recorded,
            report.first_goal_recorded,
        )
    elif args.command == "pnl":
        from goalscorer.pnl import run_pnl

        run_pnl(ctx, args.date or yesterday)
    elif args.command == "bot":
        from goalscorer.bot import run_bot

        run_bot(ctx)
    else:
        _one_off(ctx, args)


def main(argv: list[str] | None = None) -> int:
    """Parse args, run one command, alert Slack on failure."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = _parser().parse_args(argv)
    ctx = Context.from_env()
    if args.command in _SCHEDULED and not ctx.settings.enabled:
        logger.info("goalscorer mapper disabled (GOALSCORER_MAPPER_ENABLED=0); skipping %s", args.command)
        return 0
    try:
        _run(ctx, args)
    except Exception as exc:
        logger.exception("goalscorer %s failed", args.command)
        ctx.slack.post(f":x: goalscorer `{args.command}` failed on {ctx.settings.project}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
