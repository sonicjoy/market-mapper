"""Daily goalscorer PnL report: query, render PDF, upload to #goalscorer-alerts."""

from __future__ import annotations

import logging
import tempfile
from datetime import date, timedelta
from pathlib import Path

from goalscorer.context import Context
from goalscorer.pnl_pdf import PnlReport, fmt_dollar, render
from goalscorer.pnl_queries import PnlQueries, soccer_goal_prefixes

logger = logging.getLogger(__name__)


def collect(queries: PnlQueries, day: date) -> PnlReport | None:
    """Gather the report data, or None when nothing was traded on `day`."""
    daily = queries.summary(day, day)
    if not daily[1].combos:
        return None
    week_start, month_start = day - timedelta(days=6), day - timedelta(days=29)
    periods = [
        (f"7-Day Summary ({week_start} to {day})", *queries.summary(week_start, day)),
        (f"30-Day Summary ({month_start} to {day})", *queries.summary(month_start, day)),
    ]
    report = PnlReport(day, daily, periods, legs=queries.legs(day))
    if report.losers:
        report.losses = queries.losses(day, report.losers[0].leg)
    return report


def run_pnl(ctx: Context, day: date) -> Path | None:
    """Build and post the report for `day`. Returns the PDF path, or None if no combos."""
    prefixes = soccer_goal_prefixes(ctx.leagues.active().values())
    if not prefixes:
        logger.info("pnl %s: no active soccer leagues", day)
        return None
    report = collect(PnlQueries(ctx.store.client, ctx.settings.project, prefixes), day)
    if report is None:
        logger.info("pnl %s: no goalscorer combos filled", day)
        return None
    total = report.total
    path = render(report, Path(tempfile.mkdtemp()) / f"goalscorer_pnl_{day}.pdf")
    logger.info("pnl %s: %d combos, pnl %.2f → %s", day, total.combos, total.pnl, path)
    comment = (
        f"*Goalscorer PnL Report — {day}*\n{total.combos} combos | {total.won}W/{total.lost}L | "
        f"PnL {fmt_dollar(total.pnl)} | ROI {total.roi:+.1f}%"
    )
    ctx.slack.upload(path, f"Goalscorer PnL {day}", comment)
    return path
