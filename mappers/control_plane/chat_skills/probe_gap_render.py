"""Render probe_gap replies: verify tables, manual-map details, offer buttons."""

from __future__ import annotations

import re
from typing import Any

from mappers.control_plane.chat_tools_dkex_mapping import find_dkex_symbol

NEXT_STEP = {
    "actionable": "Pin in Editor, add to Cart, approve on Proposed.",
    "mapped": "Already in market_mapping.",
    "maker_lag": "Already mapped — wait for the maker to pick it up.",
    "horizon_wait": "Outside the Optic 96h horizon; re-probe closer to kickoff.",
    "expected_residual": "No Optic counterpart; nothing to map.",
    "leave_collision": "Documented collision — do not steal this canonical.",
    "needs_league": "League is not wired yet; onboard it first.",
}
_CATALOGUE_MISS = "catalogue_miss"
_NX_ANATOMY = re.compile(
    r"^NX\.F\.OPT\.(?P<token>[A-Z0-9]+)"
    r"(?:-(?P<event>\d+)-(?P<yymmdd>\d{6})"
    r"(?:-M\.O\.(?P<market>\d+)\.(?P<outcome>\d+)"
    r"(?:\.(?P<maturity>\d{8}))?)?)?",
    re.I,
)
NOT_MAPPED = "We have not mapped this."
NO_PREAMBLE = frozenset({"actionable", "mapped", "maker_lag", "leave_collision"})
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def dash(value: Any) -> str:
    """Display cell; blank becomes an em dash."""
    text = str(value or "").strip()
    return text if text else "—"


def sportsbook(row: dict[str, Any]) -> str:
    """Book from the probe row, mapping hit, or ticker/id shape."""
    book = str(row.get("sportsbook") or "")
    if not book:
        mapped = list(row.get("mapped_rows") or [])
        if mapped:
            book = str(mapped[0].get("sportsbook") or "")
    if not book:
        symbol = str(row.get("symbol") or row.get("market_ticker") or "").upper()
        if symbol.startswith("NX.F"):
            book = "crypto.com"
        elif symbol.startswith("KX"):
            book = "kalshi"
        elif symbol.startswith("0X") or (
            len(symbol) >= 32 and all(c in "0123456789ABCDEF" for c in symbol)
        ):
            book = "polymarket"
        elif symbol.isdigit() and len(symbol) >= 6:
            book = "px"
        elif _UUID.fullmatch(symbol):
            book = "novig"
        elif symbol.startswith("UDX"):
            book = "underdog"
        elif find_dkex_symbol(symbol):
            book = "dkex"
    labels = {
        "px": "Prophet X",
        "polymarket": "Polymarket",
        "polymarket_usa": "Polymarket (USA)",
        "novig": "Novig",
        "underdog": "Underdog",
        "dkex": "DraftKings Exchange",
        "crypto.com": "crypto.com",
        "kalshi": "Kalshi",
    }
    return labels.get(book.lower(), book or "?")


def next_step(verdict: str, row: dict[str, Any]) -> str:
    """Playbook next-step; catalogue miss is upstream wait, not an Optic hole."""
    kind = str(row.get("kind") or "")
    if kind == _CATALOGUE_MISS:
        return "Not in crypto_security_def; wait for upstream or map a sibling."
    if kind == "exact_score":
        return (
            "Exact score is expected residual. We only map it when Optic prices "
            "correct_score for this league, and only the Yes contract. Do not pin."
        )
    if kind == "alias_mismatch":
        return (
            "Correction card: move this crypto id onto the fixture side, "
            "then approve on Proposed."
        )
    if kind == "unmapped":
        book = str(row.get("sportsbook") or "").lower()
        if book == "polymarket":
            return "Not in market_mapping; Gamma slug/question below if the market exists."
        if book == "px":
            return "Not in market_mapping; PX fetch snapshot below if this id was ingested."
        if book == "novig":
            return "Not in market_mapping; Novig fetch snapshot below if this id was ingested."
        if book in {"polymarket_usa", "polymarket (usa)"}:
            return "Not in market_mapping; Poly US gateway fields below."
        return "Not in market_mapping (90-day window)."
    return NEXT_STEP.get(verdict, "Review the card.")


def _mapped_cell(
    row: dict[str, Any], mapped_rows: list[dict[str, Any]], codes: list[Any],
) -> str:
    """market_mapping row count. Alias hits are not a mapped count."""
    if mapped_rows:
        return f"{len(mapped_rows)} market_mapping row(s)"
    kind = str(row.get("kind") or "")
    if kind in {"unmapped", "alias_mismatch"}:
        return "0 market_mapping rows"
    return f"{len(list(row.get('tip') or []))}/{len(codes)} sides"


def verdict_table(subject: str, verdict: str, row: dict[str, Any]) -> list[str]:
    """Playbook columns plus verify or manual-map details."""
    mapped_rows = list(row.get("mapped_rows") or [])
    parts = crypto_anatomy(str(row.get("symbol") or row.get("market_ticker") or ""))
    optic = _optic_dict(row)
    fixture = str(optic.get("fixture_id") or "")
    kickoff = str(
        optic.get("start_date") or row.get("meta_event_date") or parts.get("kickoff") or ""
    )
    catalogue = str(row.get("title") or row.get("meta_name") or "")
    if not catalogue and str(row.get("kind") or "") == _CATALOGUE_MISS:
        catalogue = "not in crypto_security_def"
    if not catalogue and str(row.get("kind") or "") == "unmapped":
        catalogue = "not in market_mapping"
    codes = list(row.get("codes") or row.get("crypto_ids") or [])
    mapped = _mapped_cell(row, mapped_rows, codes)
    league = str(row.get("league") or parts.get("token") or "?")
    lines = [f"## {subject}", ""]
    if verdict not in NO_PREAMBLE:
        lines.extend([NOT_MAPPED, ""])
    lines.extend([
        "| Field | Value |",
        "|---|---|",
        f"| Verdict | **{verdict}** |",
        f"| League | {league or '?'} |",
        f"| Sportsbook | {sportsbook(row)} |",
        f"| Catalogue / title | {catalogue or '?'} |",
        f"| Optic fixture | {fixture or 'none'} |",
        f"| Kickoff | {kickoff or 'unknown'} |",
        f"| Mapped | {mapped} |",
        f"| gap_reason | `{row.get('kind') or ''}` |",
        f"| Next step | {next_step(verdict, row)} |",
    ])
    lines.extend(status_lines(row))
    lines.extend(_detail_lines(verdict, row, mapped_rows))
    return lines


def _detail_lines(
    verdict: str, row: dict[str, Any], mapped_rows: list[dict[str, Any]],
) -> list[str]:
    """Verify table, on-tip confirmation, or manual-map worksheet."""
    if mapped_rows:
        return verify_lines(row, mapped_rows)
    if verdict in {"mapped", "maker_lag", "leave_collision"}:
        return on_tip_lines(row)
    if str(row.get("kind") or "") == "exact_score":
        return []
    return manual_lines(row)


def status_lines(row: dict[str, Any]) -> list[str]:
    """Settlement line when a live market ticker was probed."""
    status = str(row.get("status") or "")
    if not status:
        return []
    result = str(row.get("result") or "")
    extra = f" (result={result})" if result else ""
    return ["", f"Status: `{status}`{extra}"]


def verify_lines(row: dict[str, Any], mapped_rows: list[dict[str, Any]]) -> list[str]:
    """Enough mapping fields for a trader to confirm the join is right."""
    first = mapped_rows[0]
    optic = _optic_dict(row)
    home = dash(first.get("home") or optic.get("home"))
    away = dash(first.get("away") or optic.get("away"))
    kickoff = dash(first.get("start_date") or optic.get("start_date") or row.get("meta_event_date"))
    fixture = dash(first.get("fixture_id") or optic.get("fixture_id"))
    game = dash(first.get("game_id"))
    lines = [
        "",
        f"**Fixture:** {home} vs {away}",
        f"**Game id:** `{game}` · **Optic fixture:** `{fixture}`",
        f"**Kickoff:** {kickoff}",
        "",
        "| Book | Source | Type | Entity | Line | Side | Selection |",
        "|---|---|---|---|---|---|---|",
    ]
    for mapped in mapped_rows[:20]:
        src = (
            mapped.get("market_ticker")
            or mapped.get("symbol")
            or mapped.get("source_selection_id")
            or mapped.get("source_event_id")
            or "—"
        )
        lines.append(
            f"| {dash(mapped.get('sportsbook'))} | `{src}` | {dash(mapped.get('market_type'))} | "
            f"{dash(mapped.get('entity'))} | {dash(mapped.get('line'))} | "
            f"{dash(mapped.get('side'))} | {dash(mapped.get('selection'))} |"
        )
    mid = str(first.get("market_id") or "")
    if mid:
        lines.append(f"- Optic market id: `{mid}`")
    return lines


def _optic_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Optic fixture payload, or empty when the probe omitted one."""
    optic = row.get("optic")
    return optic if isinstance(optic, dict) else {}


def on_tip_lines(row: dict[str, Any]) -> list[str]:
    """Tip + Optic confirmation when the symbol is already mapped."""
    codes = [str(c) for c in (row.get("codes") or row.get("crypto_ids") or []) if c]
    lines = ["", "**Already mapped**"]
    if codes:
        lines.append("- Codes: " + ", ".join(f"`{c}`" for c in codes))
    lines.extend(tip_lines(list(row.get("tip") or [])))
    lines.extend(_optic_manual(_optic_dict(row)))
    return lines


def manual_lines(row: dict[str, Any]) -> list[str]:
    """Catalogue / ticker fields a trader needs to pin the symbol by hand."""
    optic = _optic_dict(row)
    event = str(row.get("event_ticker") or "")
    market = str(row.get("market_ticker") or row.get("symbol") or "")
    codes = [str(c) for c in (row.get("codes") or row.get("crypto_ids") or []) if c]
    lines = ["", "**Map manually**"]
    if event and event != market:
        lines.append(f"- Event ticker: `{event}`")
    if market:
        lines.append(f"- Market / symbol: `{market}`")
    lines.extend(anatomy_lines(row))
    lines.extend(id_kind_lines(row))
    sub = str(row.get("sub_title") or "")
    if sub:
        lines.append(f"- Subtitle: {sub}")
    meta = str(row.get("meta_league") or "")
    if meta:
        lines.append(f"- Catalogue league: {meta}")
    contract = str(row.get("contract_type") or "")
    if contract:
        lines.append(f"- Contract: `{contract}`")
    if codes:
        lines.append("- Codes: " + ", ".join(f"`{c}`" for c in codes))
    lines.extend(tip_lines(list(row.get("tip") or [])))
    lines.extend(_optic_manual(optic))
    return lines


def tip_lines(tip: list[Any]) -> list[str]:
    """Kalshi code / crypto_id owners from the activated tip."""
    if not tip:
        return []
    bits = [_tip_bit(row) for row in tip]
    return [f"- Tip: {'; '.join(bits)}"]


def _tip_bit(row: Any) -> str:
    """One tip claim as `code` → owners (eval fixtures may pass bare names)."""
    if not isinstance(row, dict):
        return f"`{row}`"
    label = str(row.get("code") or row.get("crypto_id") or "")
    owners = [str(o) for o in (row.get("owners") or []) if o]
    dest = ", ".join(owners) if owners else "(unpinned)"
    if row.get("leave"):
        dest += " (leave)"
    return f"`{label}` → {dest}"


def crypto_anatomy(symbol: str) -> dict[str, str]:
    """Unpack NX.F.OPT.<token>-<event>-<yymmdd>-M.O.<market>.<outcome>.<maturity>."""
    m = _NX_ANATOMY.match(symbol.strip())
    if m is None:
        return {}
    token = (m.group("token") or "").upper()
    event = m.group("event") or ""
    yymmdd = m.group("yymmdd") or ""
    market = m.group("market") or ""
    outcome = m.group("outcome") or ""
    prefix = f"NX.F.OPT.{token}-{event}-{yymmdd}" if token and event and yymmdd else ""
    hint = ""
    if market == "1" and outcome in {"1", "2", "3"}:
        hint = "likely moneyline (3-way)"
    elif market and outcome:
        hint = "opaque without catalogue"
    kickoff = ""
    if len(yymmdd) == 6 and yymmdd.isdigit():
        kickoff = f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"
    return {
        "token": token,
        "event_id": event,
        "kickoff": kickoff,
        "fixture_prefix": prefix,
        "market_slot": f"{market}.{outcome}" if market else "",
        "slot_hint": hint,
        "maturity": m.group("maturity") or "",
    }


def anatomy_lines(row: dict[str, Any]) -> list[str]:
    """Ticker fields a trader can use when the catalogue row is missing."""
    symbol = str(row.get("symbol") or row.get("market_ticker") or "")
    parts = crypto_anatomy(symbol)
    if not parts:
        return []
    lines: list[str] = []
    if parts["fixture_prefix"]:
        lines.append(f"- Fixture prefix: `{parts['fixture_prefix']}`")
    if parts["token"]:
        lines.append(f"- NX token: `{parts['token']}`")
    if parts["event_id"]:
        lines.append(f"- Crypto event id: `{parts['event_id']}`")
    if parts["kickoff"]:
        lines.append(f"- Kickoff (from ticker): {parts['kickoff']}")
    if parts["market_slot"]:
        extra = f" ({parts['slot_hint']})" if parts["slot_hint"] else ""
        lines.append(f"- Market / outcome slot: `M.O.{parts['market_slot']}`{extra}")
    if parts["maturity"]:
        lines.append(f"- Maturity: `{parts['maturity']}`")
    return lines


def id_kind_lines(row: dict[str, Any]) -> list[str]:
    """Polymarket / PX id anatomy when the paste is not an NX.F symbol."""
    kind = str(row.get("id_kind") or "")
    if not kind or kind == "unknown":
        return []
    lines = [f"- Id kind: `{kind}`"]
    norm = str(row.get("norm_id") or "")
    symbol = str(row.get("symbol") or row.get("market_ticker") or "")
    if norm and norm != symbol:
        lines.append(f"- Normalized: `{norm}`")
    slug = str(row.get("slug") or "")
    if slug:
        lines.append(f"- Slug: `{slug}`")
    outcomes = [str(o) for o in (row.get("outcomes") or []) if o]
    if outcomes:
        lines.append("- Outcomes: " + ", ".join(f"`{o}`" for o in outcomes[:8]))
    tour = str(row.get("tournament") or "")
    if tour:
        lines.append(f"- PX tournament: {tour}")
    ntype = str(row.get("novig_type") or "")
    if ntype:
        lines.append(f"- Novig type: `{ntype}`")
    event_id = str(row.get("event_id") or "")
    if event_id and event_id != symbol:
        lines.append(f"- Novig event: `{event_id}`")
    smt = str(row.get("sports_market_type") or "")
    if smt:
        lines.append(f"- Poly US market type: `{smt}`")
    suffix = str(row.get("suffix") or "")
    if suffix:
        lines.append(f"- Outcome suffix: `{suffix}`")
    return lines


def _optic_manual(optic: dict[str, Any]) -> list[str]:
    """Optic counterpart line for probe confirmation."""
    if optic and (optic.get("home") or optic.get("away") or optic.get("fixture_id")):
        return [
            f"- Optic: `{dash(optic.get('fixture_id'))}` "
            f"{dash(optic.get('home'))} vs {dash(optic.get('away'))}"
        ]
    return ["- Optic: none"]


def manual_prefill(row: dict[str, Any], book: str, alias_kind: str) -> dict[str, Any] | None:
    """Entry fields when the trader must pin by hand (league + code)."""
    league = str(row.get("league") or "")
    unknown = [str(c) for c in (row.get("unknown_codes") or []) if c]
    codes = unknown or [str(c) for c in (row.get("codes") or row.get("crypto_ids") or []) if c]
    if not league or not codes:
        return None
    return {
        "tab": "alias",
        "league": league,
        "sportsbook": book,
        "code": codes[0],
        "canonical_key": "",
        "entity_name": "",
        "entity_type": "team",
        "alias_kind": alias_kind,
    }


