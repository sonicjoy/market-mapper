"""Render the goalscorer PnL report as a landscape A4 PDF.

fpdf2 core fonts are latin-1 only, so all text here is ASCII (tickers, codes,
plain punctuation).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from fpdf import FPDF

from goalscorer.pnl_queries import LegRow, LossCombo, SeriesRow

GREEN = (34, 139, 34)
RED = (200, 50, 50)
INK = (30, 30, 30)
MUTED = (100, 100, 100)

SERIES_NAMES = {"KXEPLGOAL": "EPL", "KXLALIGAGOAL": "La Liga", "KXUCLGOAL": "UCL"}
MARKET_LABELS = {
    "KXEPLGOAL": "EPL Goal",
    "KXLALIGAGOAL": "Liga Goal",
    "KXUCLGOAL": "UCL Goal",
    "KXEPLFIRSTGOAL": "EPL First Goal",
    "KXLALIGAFIRSTGOAL": "Liga First Goal",
    "KXUCLFIRSTGOAL": "UCL First Goal",
    "KXEPLGAME": "EPL ML",
    "KXLALIGAGAME": "Liga ML",
    "KXEPLTOTAL": "EPL Total",
    "KXLALIGATOTAL": "Liga Total",
    "KXEPL1H": "EPL 1H ML",
    "KXEPL1HTOTAL": "EPL 1H Total",
    "KXEPLCORNERS": "EPL Corners",
    "KXEPLTCORNERS": "EPL Team Corners",
}
SUMMARY_COLS = ["League", "Combos", "Won", "Lost", "Stakes", "Risk", "Fees", "PnL", "ROI"]
SUMMARY_WIDTHS = [40, 20, 18, 18, 38, 38, 28, 32, 22]
LEG_COLS = ["Player Code", "Fixture", "Combos", "Stakes", "Risk", "PnL"]
LEG_WIDTHS = [52, 38, 22, 42, 42, 36]
LOSS_COLS = ["Combo Ticker", "PnL", "Stake", "Risk", "Other Legs"]
LOSS_WIDTHS = [88, 24, 24, 28, 86]


@dataclass
class PnlReport:
    """Everything the PDF shows."""

    day: date
    daily: tuple[list[SeriesRow], SeriesRow]
    periods: list[tuple[str, list[SeriesRow], SeriesRow]]
    legs: list[LegRow] = field(default_factory=list)
    losses: list[LossCombo] = field(default_factory=list)

    @property
    def total(self) -> SeriesRow:
        """The day's rollup row."""
        return self.daily[1]

    @property
    def losers(self) -> list[LegRow]:
        """Ten worst legs by PnL."""
        return sorted((leg for leg in self.legs if leg.pnl < 0), key=lambda leg: leg.pnl)[:10]


def series_name(series: str) -> str:
    """Short display name for one or more comma-separated goal series."""
    parts = [s.strip() for s in series.split(",") if s.strip()]
    return " + ".join(_series_label(s) for s in parts)


def _series_label(series: str) -> str:
    """EPL for KXEPLGOAL, EPL First Goal for KXEPLFIRSTGOAL."""
    if series.endswith("FIRSTGOAL"):
        return _series_label(series.removesuffix("FIRSTGOAL") + "GOAL") + " First Goal"
    return SERIES_NAMES.get(series, series.removeprefix("KX").removesuffix("GOAL"))


def fmt_dollar(value: float) -> str:
    """+$1,234 / -$0.50 style."""
    sign = "+" if value >= 0 else "-"
    magnitude = abs(value)
    return f"{sign}${magnitude:,.0f}" if magnitude >= 1 else f"{sign}${magnitude:,.2f}"


def split_leg(ticker: str) -> tuple[str, str]:
    """(player code, fixture teams) from a goal leg ticker; a first goalscorer code is tagged FG."""
    parts = ticker.split("-")
    if len(parts) < 3:
        return ticker, ""
    code = "-".join(parts[2:]) + (" FG" if parts[0].endswith("FIRSTGOAL") else "")
    return code, re.sub(r"^\d+[A-Z]{3}\d+", "", parts[1])


def describe_leg(ticker: str) -> str:
    """Readable label for any combo leg."""
    parts = ticker.split("-")
    if len(parts) < 2:
        return ticker
    label = MARKET_LABELS.get(parts[0], parts[0].removeprefix("KX"))
    teams = re.sub(r"^\d+[A-Z]{3}\d+", "", parts[1])
    home, away = (teams[:3], teams[3:6]) if len(teams) >= 6 else (teams, "")
    selection = "-".join(parts[2:])
    if selection and selection.replace(".", "").isdigit():
        return f"{label} {home}/{away} o{selection}"
    return f"{label} {selection}" if selection else f"{label} {home}/{away}"


class _Doc(FPDF):
    """FPDF with the report's header, footer and table helpers."""

    def __init__(self, day: date) -> None:
        super().__init__(orientation="L", format="A4")
        self.day = day

    def header(self) -> None:
        """Title block on the first page."""
        if self.page_no() != 1:
            return
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(*INK)
        self.cell(0, 10, "Goalscorer PnL Report", new_x="LMARGIN", new_y="NEXT", align="C")
        self.set_font("Helvetica", "", 11)
        self.set_text_color(*MUTED)
        self.cell(0, 6, self.day.isoformat(), new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(4)

    def footer(self) -> None:
        """Page x/y."""
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section(self, title: str) -> None:
        """Section heading with a rule."""
        self.ln(6)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*INK)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(66, 133, 244)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def table_header(self, cols: Sequence[str], widths: Sequence[float]) -> None:
        """Shaded header row."""
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(240, 240, 245)
        self.set_text_color(60, 60, 60)
        for col, width in zip(cols, widths, strict=True):
            self.cell(width, 6, col, fill=True, align="C")
        self.ln()

    def table_row(self, values: Sequence[str], widths: Sequence[float], total: bool = False) -> None:
        """One row; $ values coloured by sign, totals bold and shaded."""
        self.set_font("Helvetica", "B" if total else "", 8)
        self.set_fill_color(230, 245, 230)
        for value, width in zip(values, widths, strict=True):
            colour = GREEN if value.startswith("+$") else RED if value.startswith("-$") else INK
            self.set_text_color(*colour)
            self.cell(width, 5.5, value, fill=total, align="C")
        self.set_text_color(*INK)
        self.ln()

    def rule(self, width: float) -> None:
        """Thin separator above a total row."""
        self.set_draw_color(180, 180, 180)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.l_margin + width, self.get_y())
        self.ln(1)


def _summary_values(row: SeriesRow, label: str) -> list[str]:
    """Cells for one summary row."""
    return [
        label,
        str(row.combos),
        str(row.won),
        str(row.lost),
        f"${row.stakes:,.0f}",
        f"${row.risk:,.0f}",
        f"${row.fees:,.2f}",
        fmt_dollar(row.pnl),
        f"{row.roi:+.1f}%",
    ]


def _hero(pdf: _Doc, total: SeriesRow) -> None:
    """Headline PnL and one-line stats."""
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(*(GREEN if total.pnl >= 0 else RED))
    pdf.cell(0, 14, fmt_dollar(total.pnl), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*MUTED)
    line = (
        f"{total.combos} combos  |  {total.won}W / {total.lost}L  |  Stakes ${total.stakes:,.0f}  |  "
        f"Risk ${total.risk:,.0f}  |  ROI {total.roi:+.1f}%"
    )
    pdf.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(2)


def _summary_table(pdf: _Doc, title: str, rows: list[SeriesRow], total: SeriesRow) -> None:
    """Per-series table with a total row."""
    pdf.section(title)
    pdf.table_header(SUMMARY_COLS, SUMMARY_WIDTHS)
    for row in rows:
        pdf.table_row(_summary_values(row, series_name(row.series)), SUMMARY_WIDTHS)
    pdf.rule(sum(SUMMARY_WIDTHS))
    pdf.table_row(_summary_values(total, "TOTAL"), SUMMARY_WIDTHS, total=True)


def _leg_table(pdf: _Doc, title: str, legs: list[LegRow]) -> None:
    """Leg table (code, fixture, combos, stakes, risk, PnL)."""
    pdf.section(title)
    pdf.table_header(LEG_COLS, LEG_WIDTHS)
    for leg in legs:
        code, teams = split_leg(leg.leg)
        values = [code, teams, str(leg.combos), f"${leg.stakes:,.0f}", f"${leg.risk:,.0f}", fmt_dollar(leg.pnl)]
        pdf.table_row(values, LEG_WIDTHS)


def _loss_row(pdf: _Doc, loss: LossCombo) -> None:
    """One losing combo, its other legs stacked in the last column."""
    legs = [describe_leg(leg) for leg in loss.legs] or ["(solo)"]
    height = 5 * len(legs)
    if pdf.get_y() + height > pdf.h - pdf.b_margin:
        pdf.add_page()
        pdf.table_header(LOSS_COLS, LOSS_WIDTHS)
    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_font("Helvetica", "", 6)
    pdf.set_text_color(*INK)
    pdf.cell(LOSS_WIDTHS[0], height, loss.combo, align="C")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*(GREEN if loss.pnl >= 0 else RED))
    pdf.cell(LOSS_WIDTHS[1], height, fmt_dollar(loss.pnl), align="C")
    pdf.set_text_color(*INK)
    pdf.cell(LOSS_WIDTHS[2], height, f"${loss.stakes:,.0f}", align="C")
    pdf.cell(LOSS_WIDTHS[3], height, f"${loss.risk:,.0f}", align="C")
    legs_x = pdf.get_x()
    for i, label in enumerate(legs):
        pdf.set_xy(legs_x, y + i * 5)
        pdf.cell(LOSS_WIDTHS[4], 5, f"  {label}")
    pdf.set_draw_color(200, 200, 200)
    pdf.line(x, y + height, x + sum(LOSS_WIDTHS), y + height)
    pdf.set_xy(x, y + height + 1)


def render(report: PnlReport, path: Path) -> Path:
    """Write the report PDF to `path`."""
    pdf = _Doc(report.day)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    _hero(pdf, report.total)
    _summary_table(pdf, f"1D Summary ({report.day})", *report.daily)
    for title, rows, total in report.periods:
        _summary_table(pdf, title, rows, total)
    _leg_table(pdf, "Top 10 Legs by Combo Count", sorted(report.legs, key=lambda leg: -leg.combos)[:10])
    winners = sorted((leg for leg in report.legs if leg.pnl > 0), key=lambda leg: -leg.pnl)[:10]
    _leg_table(pdf, "Top 10 Winning Legs", winners)
    if report.losers:
        _leg_table(pdf, "Losing Legs", report.losers)
    if report.losses:
        pdf.section(f"Loss Breakdown: {split_leg(report.losers[0].leg)[0]}")
        pdf.table_header(LOSS_COLS, LOSS_WIDTHS)
        for loss in report.losses:
            _loss_row(pdf, loss)
    pdf.output(str(path))
    return path
