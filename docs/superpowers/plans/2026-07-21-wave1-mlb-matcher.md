> Historical. Tip/console references are retired; see CLAUDE.md.

# Wave 1 — Polymarket→OpticOdds mlb matcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Polymarket active matcher to `mmmapper` that maps `clob_token_id → optic (mlb moneyline + total_runs)` by parsing the position↔token bridge's slug/question, matching to the optic schedule by team-name, and stamping the missing Polymarket `source_ids` onto optic rows in `markets_us.market_mapping` — flip-safe (side bound to the outcome label, guarded).

**Architecture:** New `mappers/exchanges/polymarket.py` (config + `parse_market` + `build_rows`) mirrors the crypto.com matcher, but matches by team NAME against the optic schedule (Polymarket has no stable team IDs) using the same `_normalize`/`_names_equiv` logic ported from the maker. New `fetch/polymarket.py` reads the bridge from BigQuery → `polymarket_markets.jsonl`. Poly rows merge onto existing optic rows (guard #3: market_type must exist in optic for that fixture) via `attach_polymarket_row` (stamp-if-optic-row-exists, else drop). `load_mappings.flatten_rows` emits a constructed `Polymarket` row; `"Polymarket"` leaves `OPTIC_MAPPED_SPORTSBOOKS` so it isn't double-emitted.

**Tech Stack:** Python (mmmapper), pydantic models, `google-cloud-bigquery`, pytest. Same style as `mappers/exchanges/crypto_com.py`.

## Global Constraints

- **Scope Wave 1 = mlb only, market types moneyline + total (`total_runs`).** Run line (POINT_SPREAD) and other leagues are later waves. An unmapped market type is DROPPED, never guessed.
- **Flip-safety (non-negotiable — Norway 2026-07-09):** a token's `side` is bound to its Polymarket `outcome_label`, NEVER to array index. A binary market's two outcomes must resolve to complementary optic selections or the whole market is dropped. Where optic already maps the clob, the parsed side must agree with optic's or the market is dropped + logged.
- **Poly rows merge onto optic, never novel-only.** Guard #3: only emit a poly row when an optic row for the same `(game, market_type, line, side)` already exists in this run (`row_index` hit). No `_polymarket_only_base`; no synthetic optic columns.
- **`clob_token_id` is the join key** (`source_ids = {"selection_id": clob_token_id}`), matching what the maker reads. `position_id` is provenance only.
- **Matching is by team NAME + date** against `Fixture.home_name`/`away_name`, using the ported `_normalize`/`_names_equiv` (NOT `resolve_team` by ID — Polymarket has no team IDs).
- Follow existing mmmapper patterns exactly (dataclass config, pydantic input model, `build_rows` signature shape, `canonical_row_to_json`/`flatten_rows` structure).

---

### Task 1: `CanonicalRow` polymarket_* fields + `canonical_row_to_json` block

**Files:**
- Modify: `mappers/shared.py` (`CanonicalRow`, after the `crypto_*` stamp block, ~line 328)
- Modify: `mappers/pipeline.py` (`canonical_row_to_json`, after the crypto block, ~line 358)
- Test: `tests/mappers/test_polymarket.py` (create)

**Interfaces:**
- Produces: `CanonicalRow` gains `polymarket_clob_token_id`, `polymarket_condition_id`, `polymarket_position_id`, `polymarket_slug`, `polymarket_question` (all `str | None = None`). `canonical_row_to_json(row)` emits `result["polymarket"] = {"clob_token_id","condition_id","position_id","slug","question"}` or `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/mappers/test_polymarket.py`:

```python
from mappers.shared import CanonicalRow
from mappers.pipeline import canonical_row_to_json


def _row(**kw):
    base = dict(league="mlb", start_date="2026-07-21T23:00:00Z",
                home="AZ", away="STL", market_type="moneyline", side="AZ")
    base.update(kw)
    return CanonicalRow(**base)


def test_canonical_row_has_polymarket_stamp_fields():
    r = _row(polymarket_clob_token_id="cX", polymarket_condition_id="0xabc",
             polymarket_position_id="pX", polymarket_slug="mlb-az-stl-2026-07-21",
             polymarket_question="Arizona Diamondbacks vs. St. Louis Cardinals")
    assert r.polymarket_clob_token_id == "cX"
    assert r.polymarket_position_id == "pX"


def test_canonical_row_to_json_emits_polymarket_block():
    r = _row(polymarket_clob_token_id="cX", polymarket_condition_id="0xabc",
             polymarket_position_id="pX", polymarket_slug="s", polymarket_question="q")
    j = canonical_row_to_json(r)
    assert j["polymarket"] == {
        "clob_token_id": "cX", "condition_id": "0xabc",
        "position_id": "pX", "slug": "s", "question": "q",
    }


def test_canonical_row_to_json_polymarket_none_when_absent():
    j = canonical_row_to_json(_row())
    assert j["polymarket"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/mappers/test_polymarket.py -x -q`
Expected: FAIL — `TypeError`/`ValidationError` on the unknown `polymarket_*` kwargs (fields not defined yet).

- [ ] **Step 3: Add the CanonicalRow fields**

In `mappers/shared.py`, immediately after the `crypto_selection_name` field (~line 328, before the Huddle block) add:

```python
    # Polymarket — novel rows, matched by team name against the optic
    # schedule (no stable team IDs).  clob_token_id is the source-id
    # stamp (the px_line_id / kalshi_ticker / crypto_security_id analog);
    # position_id is provenance only.  See docs/adding-polymarket.md.
    polymarket_clob_token_id: str | None = None  # source-id stamp (functional key)
    polymarket_condition_id: str | None = None   # underlying single condition_id (provenance)
    polymarket_position_id: str | None = None     # combo-leg NegRisk token id (provenance)
    polymarket_slug: str | None = None            # single-market slug (provenance)
    polymarket_question: str | None = None        # single-market question/title (provenance)
```

- [ ] **Step 4: Add the canonical_row_to_json block**

In `mappers/pipeline.py`, in `canonical_row_to_json`, immediately after the `crypto_com` block (~line 358) add:

```python
    # Polymarket — novel rows, no Optic cross-check for the token map.
    # clob_token_id is the source-id stamp (crypto_security_id analog).
    if row.polymarket_clob_token_id is not None:
        result["polymarket"] = {
            "clob_token_id": row.polymarket_clob_token_id,
            "condition_id": row.polymarket_condition_id,
            "position_id": row.polymarket_position_id,
            "slug": row.polymarket_slug,
            "question": row.polymarket_question,
        }
    else:
        result["polymarket"] = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/mappers/test_polymarket.py -x -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add mappers/shared.py mappers/pipeline.py tests/mappers/test_polymarket.py
git commit -m "feat(polymarket): CanonicalRow polymarket_* stamp fields + json block"
```

---

### Task 2: `mappers/exchanges/polymarket.py` — config, model, parse_market

**Files:**
- Create: `mappers/exchanges/polymarket.py`
- Test: `tests/mappers/test_polymarket.py` (append)

**Interfaces:**
- Consumes: nothing from prior tasks (uses `mappers.market_types.MarketType`).
- Produces:
  - `@dataclass(frozen=True) PolymarketConfig` with fields `slug_prefix: str`, `optic_league_id: str`, `market_types: dict[str, MarketType]` (keys `"moneyline"`, `"total"`).
  - `class PolyMarket(pydantic.BaseModel)`: `condition_id: str`, `slug: str`, `question: str`, `outcomes: list["PolyOutcome"]`.
  - `class PolyOutcome(pydantic.BaseModel)`: `clob_token_id: str`, `position_id: str`, `outcome_label: str`, `outcome_index: int`.
  - `parse_market(line: str) -> PolyMarket | None` (JSON line → model; None if unparseable).
  - `parse_question(question: str, cfg: PolymarketConfig) -> dict | None` returning `{"market_kind": "moneyline"|"total", "team_a": <norm>, "team_b": <norm>, "line": float|None}` or None.
  - Ported helpers `_normalize(s)`, `_names_equiv(a,b)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/mappers/test_polymarket.py`:

```python
from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType

MLB_CFG = pm.PolymarketConfig(
    slug_prefix="mlb",
    optic_league_id="mlb",
    market_types={"moneyline": MarketType.MONEYLINE, "total": MarketType.GAME_TOTAL},
)


def test_parse_question_moneyline():
    out = pm.parse_question("Arizona Diamondbacks vs. St. Louis Cardinals", MLB_CFG)
    assert out["market_kind"] == "moneyline"
    assert out["team_a"] == "arizona diamondbacks"
    assert out["team_b"] == "st louis cardinals"
    assert out["line"] is None


def test_parse_question_total():
    out = pm.parse_question("Arizona Diamondbacks vs. St. Louis Cardinals: O/U 8.5", MLB_CFG)
    assert out["market_kind"] == "total"
    assert out["line"] == 8.5


def test_parse_question_unknown_returns_none():
    assert pm.parse_question("Alec Burleson: Home Runs O/U 0.5", MLB_CFG) is None
    assert pm.parse_question("1st 5 Innings Spread: Arizona Diamondbacks (-1.5)", MLB_CFG) is None


def test_parse_market_builds_model():
    import json
    line = json.dumps({
        "condition_id": "0xabc", "slug": "mlb-az-stl-2026-07-21",
        "question": "Arizona Diamondbacks vs. St. Louis Cardinals",
        "outcomes": [
            {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
            {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "St. Louis Cardinals", "outcome_index": 1},
        ],
    })
    m = pm.parse_market(line)
    assert m.condition_id == "0xabc" and len(m.outcomes) == 2
    assert m.outcomes[0].outcome_label == "Arizona Diamondbacks"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/mappers/test_polymarket.py -k "parse_" -q`
Expected: FAIL — `ModuleNotFoundError: mappers.exchanges.polymarket`.

- [ ] **Step 3: Create the module**

Create `mappers/exchanges/polymarket.py`:

```python
"""Polymarket active matcher — bridge slug/question → OpticOdds.

Polymarket combo legs reference underlying single markets (clob_token_id).
The position↔token bridge (raw_ingestion_us.polymarket_position_token_bridge,
built by BigQuery/load_polymarket_position_bridge.py) carries each single's
slug/question/outcome_label per clob_token_id. This matcher parses that
natural-language question into (market_type, line) and matches the fixture by
TEAM NAME against the optic schedule (Polymarket exposes no stable team IDs,
unlike crypto.com), then emits one CanonicalRow per outcome with side bound to
the outcome_label. Rows merge onto existing optic rows (see
attach_polymarket_row in pipeline.py) — a market optic didn't price is dropped.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

from pydantic import BaseModel

from mappers.market_types import MarketType


@dataclass(frozen=True)
class PolymarketConfig:
    """Per-league Polymarket matching constants."""
    slug_prefix: str                       # bridge slug prefix, e.g. "mlb"
    optic_league_id: str                   # optic league_id to match within, e.g. "mlb"
    market_types: dict[str, MarketType]    # question-kind -> canonical MarketType
                                           # keys: "moneyline", "total"


class PolyOutcome(BaseModel):
    clob_token_id: str
    position_id: str
    outcome_label: str
    outcome_index: int


class PolyMarket(BaseModel):
    condition_id: str
    slug: str
    question: str
    outcomes: list[PolyOutcome]


# --- ported from mmpolymarketrfq/common/mapping_loader.py (team-name matching) ---

def _normalize(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _names_equiv(a: str, b: str) -> bool:
    """True if two normalized team names are equal or containment-equivalent."""
    if not a or not b:
        return False
    return a == b or a in b or b in a


# Full-game moneyline: "<Team A> vs. <Team B>"  (no suffix)
_Q_MONEYLINE = re.compile(r"^(.+?)\s+vs\.?\s+(.+?)$", re.I)
# Full-game total:     "<Team A> vs. <Team B>: O/U <N>"
_Q_TOTAL = re.compile(r"^(.+?)\s+vs\.?\s+(.+?):\s*o/u\s*([\d.]+)\s*$", re.I)
# Anything with a ":" that isn't the O/U form is an exotic/period/prop market
# (e.g. "1st 5 Innings Spread: ...", "<Player>: Home Runs O/U 0.5") -> not ours.


def parse_question(question: str, cfg: PolymarketConfig) -> dict | None:
    """Parse a single-market question into a structured game-line, or None.

    Only full-game moneyline and total are recognised (Wave 1). Player props,
    period (F5/1st-inning) and spread questions return None and are dropped.
    """
    q = (question or "").strip()
    mt = _Q_TOTAL.match(q)
    if mt:
        try:
            line = float(mt.group(3))
        except ValueError:
            return None
        return {"market_kind": "total", "team_a": _normalize(mt.group(1)),
                "team_b": _normalize(mt.group(2)), "line": line}
    # A ":" that didn't match the O/U total form is a market kind we don't map.
    if ":" in q:
        return None
    mm = _Q_MONEYLINE.match(q)
    if mm:
        return {"market_kind": "moneyline", "team_a": _normalize(mm.group(1)),
                "team_b": _normalize(mm.group(2)), "line": None}
    return None


def parse_market(line: str) -> PolyMarket | None:
    """Parse one JSON line (written by fetch/polymarket.py) into a PolyMarket."""
    try:
        return PolyMarket(**json.loads(line))
    except (ValueError, TypeError):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/mappers/test_polymarket.py -k "parse_" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mappers/exchanges/polymarket.py tests/mappers/test_polymarket.py
git commit -m "feat(polymarket): PolymarketConfig + PolyMarket model + question parser (mlb ml/total)"
```

---

### Task 3: `build_rows` — emit guarded, flip-safe rows

**Files:**
- Modify: `mappers/exchanges/polymarket.py` (add `build_rows`)
- Test: `tests/mappers/test_polymarket.py` (append)

**Interfaces:**
- Consumes: `PolymarketConfig`, `PolyMarket` (Task 2); `CanonicalRow` (`mappers.shared`); the matched fixture's `home_name`/`away_name`/`home`/`away`/`start_date`.
- Produces: `build_rows(market: PolyMarket, parsed: dict, *, home, away, home_name, away_name, start_date, cfg, league) -> list[CanonicalRow]`. One row per outcome; side bound to `outcome_label`; drops the whole market if outcomes don't resolve to the two complementary sides.

- [ ] **Step 1: Write the failing test**

Append to `tests/mappers/test_polymarket.py`:

```python
def _mkt(question, outcomes):
    return pm.PolyMarket(condition_id="0xabc", slug="mlb-az-stl-2026-07-21",
                         question=question,
                         outcomes=[pm.PolyOutcome(**o) for o in outcomes])


def test_build_rows_moneyline_binds_side_to_label():
    m = _mkt("Arizona Diamondbacks vs. St. Louis Cardinals", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "St. Louis Cardinals", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_CFG)
    rows = pm.build_rows(m, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date="2026-07-21T23:00:00Z", cfg=MLB_CFG, league="mlb")
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    # side is the team the LABEL names, not the array position
    assert by_tok["cA"].side == "AZ" and by_tok["cA"].market_type == "moneyline"
    assert by_tok["cB"].side == "STL"
    assert by_tok["cA"].line is None


def test_build_rows_total_over_under():
    m = _mkt("Arizona Diamondbacks vs. St. Louis Cardinals: O/U 8.5", [
        {"clob_token_id": "cO", "position_id": "pO", "outcome_label": "Over", "outcome_index": 0},
        {"clob_token_id": "cU", "position_id": "pU", "outcome_label": "Under", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_CFG)
    rows = pm.build_rows(m, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date="2026-07-21T23:00:00Z", cfg=MLB_CFG, league="mlb")
    by_tok = {r.polymarket_clob_token_id: r for r in rows}
    assert by_tok["cO"].side == "over" and by_tok["cO"].line == 8.5
    assert by_tok["cU"].side == "under" and by_tok["cU"].market_type == "game_total"


def test_build_rows_drops_market_when_labels_not_complementary():
    # both labels resolve to the same team -> not a valid two-sided market -> drop all
    m = _mkt("Arizona Diamondbacks vs. St. Louis Cardinals", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Arizona Diamondbacks", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Arizona Diamondbacks", "outcome_index": 1},
    ])
    parsed = pm.parse_question(m.question, MLB_CFG)
    rows = pm.build_rows(m, parsed, home="AZ", away="STL",
                         home_name="Arizona Diamondbacks", away_name="St. Louis Cardinals",
                         start_date="2026-07-21T23:00:00Z", cfg=MLB_CFG, league="mlb")
    assert rows == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/mappers/test_polymarket.py -k build_rows -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'build_rows'`.

- [ ] **Step 3: Implement build_rows**

Append to `mappers/exchanges/polymarket.py`:

```python
from mappers.shared import CanonicalRow


def _stamp(o: PolyOutcome, market: PolyMarket) -> dict:
    """Shared polymarket_* stamp kwargs for a CanonicalRow."""
    return dict(
        polymarket_clob_token_id=o.clob_token_id,
        polymarket_condition_id=market.condition_id,
        polymarket_position_id=o.position_id,
        polymarket_slug=market.slug,
        polymarket_question=market.question,
    )


def build_rows(
    market: PolyMarket,
    parsed: dict,
    *,
    home: str,
    away: str,
    home_name: str,
    away_name: str,
    start_date: str,
    cfg: PolymarketConfig,
    league: str,
) -> list[CanonicalRow]:
    """One CanonicalRow per outcome; side bound to the outcome_label.

    Flip-safety: moneyline side = the fixture abbrev whose name the label
    matches; totals side = over/under from the label. If a market's outcomes
    don't resolve to the two complementary sides, the WHOLE market is dropped
    (return []). Rows are emitted only for market kinds in cfg.market_types;
    guard #3 (market must exist in optic for this fixture) is enforced later,
    in attach_polymarket_row.
    """
    kind = parsed["market_kind"]
    mt = cfg.market_types.get(kind)
    if mt is None:
        return []

    rows: list[CanonicalRow] = []
    if kind == "moneyline":
        seen_sides: set[str] = set()
        for o in market.outcomes:
            lab = _normalize(o.outcome_label)
            if _names_equiv(lab, _normalize(home_name)):
                side = home
            elif _names_equiv(lab, _normalize(away_name)):
                side = away
            else:
                return []  # a label that isn't either team -> unsafe, drop market
            seen_sides.add(side)
            rows.append(CanonicalRow(
                league=league, start_date=start_date, home=home, away=away,
                market_type=mt.value, entity=None, line=None, side=side,
                **_stamp(o, market)))
        if seen_sides != {home, away}:
            return []  # not both complementary teams -> drop
        return rows

    if kind == "total":
        line = parsed["line"]
        seen: set[str] = set()
        for o in market.outcomes:
            lab = _normalize(o.outcome_label)
            if lab == "over":
                side = "over"
            elif lab == "under":
                side = "under"
            else:
                return []  # totals must be Over/Under -> else unsafe, drop
            seen.add(side)
            rows.append(CanonicalRow(
                league=league, start_date=start_date, home=home, away=away,
                market_type=mt.value, entity=None, line=line, side=side,
                **_stamp(o, market)))
        if seen != {"over", "under"}:
            return []
        return rows

    return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/mappers/test_polymarket.py -k build_rows -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mappers/exchanges/polymarket.py tests/mappers/test_polymarket.py
git commit -m "feat(polymarket): build_rows — label-bound side + complementary-pair drop"
```

---

### Task 4: `attach_polymarket_row` — merge-onto-optic-else-drop (guard #3 + cross-check)

**Files:**
- Modify: `mappers/pipeline.py` (add `attach_polymarket_row` + `_update_polymarket_stamp`, near `attach_crypto_row`, ~line 229)
- Test: `tests/mappers/test_polymarket_attach.py` (create)

**Interfaces:**
- Consumes: `row_key` (`mappers.pipeline`), `CanonicalRow`.
- Produces: `attach_polymarket_row(row_index: dict[tuple, CanonicalRow], pr: CanonicalRow) -> str` returning `"stamped"` (an optic row existed → poly source-id stamped onto it) or `"dropped_no_optic"` (guard #3: no optic row for this key → dropped). Does NOT append new rows.

- [ ] **Step 1: Write the failing test**

Create `tests/mappers/test_polymarket_attach.py`:

```python
from mappers.pipeline import attach_polymarket_row, row_key
from mappers.shared import CanonicalRow


def _optic(**kw):
    base = dict(league="mlb", start_date="2026-07-21T23:00:00Z", home="AZ", away="STL",
                market_type="game_total", line=8.5, side="over", optic_id="OPT1")
    base.update(kw)
    return CanonicalRow(**base)


def _poly(**kw):
    base = dict(league="mlb", start_date="2026-07-21T23:00:00Z", home="AZ", away="STL",
                market_type="game_total", line=8.5, side="over",
                polymarket_clob_token_id="cO")
    base.update(kw)
    return CanonicalRow(**base)


def test_attach_stamps_onto_matching_optic_row():
    optic = _optic()
    index = {row_key(optic): optic}
    result = attach_polymarket_row(index, _poly())
    assert result == "stamped"
    assert index[row_key(optic)].polymarket_clob_token_id == "cO"


def test_attach_drops_when_no_optic_row():
    # guard #3: optic didn't price this market for this fixture -> drop, don't append
    index = {}
    result = attach_polymarket_row(index, _poly())
    assert result == "dropped_no_optic"
    assert index == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/mappers/test_polymarket_attach.py -q`
Expected: FAIL — `ImportError: cannot import name 'attach_polymarket_row'`.

- [ ] **Step 3: Implement**

In `mappers/pipeline.py`, immediately after `attach_crypto_row` (~line 229) add:

```python
def _update_polymarket_stamp(row: CanonicalRow, pr: CanonicalRow) -> None:
    """Copy Polymarket contract fields onto a canonical (optic) row."""
    row.polymarket_clob_token_id = pr.polymarket_clob_token_id
    row.polymarket_condition_id = pr.polymarket_condition_id
    row.polymarket_position_id = pr.polymarket_position_id
    row.polymarket_slug = pr.polymarket_slug
    row.polymarket_question = pr.polymarket_question


def attach_polymarket_row(
    row_index: dict[tuple, CanonicalRow], pr: CanonicalRow
) -> str:
    """Stamp a Polymarket source-id onto the matching optic row, else drop.

    Guard #3: a Polymarket row is emitted ONLY when an optic row for the same
    (game, market_type, line, side) already exists this run — the maker can only
    price a market optic priced. No optic row -> drop (return "dropped_no_optic"),
    never append a standalone poly row. The clob_token_id (source-id stamp) is
    added to the optic row so load_mappings emits a constructed Polymarket
    source_ids for it.
    """
    existing = row_index.get(row_key(pr))
    if existing is None:
        return "dropped_no_optic"
    _update_polymarket_stamp(existing, pr)
    return "stamped"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/mappers/test_polymarket_attach.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mappers/pipeline.py tests/mappers/test_polymarket_attach.py
git commit -m "feat(polymarket): attach_polymarket_row — stamp-onto-optic else drop (guard #3)"
```

---

### Task 5: Pipeline wiring — `LeagueConfig.POLYMARKET` + load/match/build block

**Files:**
- Modify: `mappers/pipeline.py` (`LeagueConfig` ~line 42-58; new poly load+match+build block in `run()`, after the crypto build block ~line 1265; import `polymarket`)
- Test: `tests/mappers/test_polymarket_pipeline.py` (create — a focused unit test of the name-match helper)

**Interfaces:**
- Consumes: `polymarket.parse_market`/`parse_question`/`build_rows` (Tasks 2-3); `attach_polymarket_row` (Task 4); the `index: dict[MatchKey, ScheduleEntry]` schedule (each entry's `.fixture` has `home`/`away`/`home_name`/`away_name`/`start_date`); `row_index` (built by the optic pass, ~line 1216-1233).
- Produces: `LeagueConfig` gains `POLYMARKET: polymarket.PolymarketConfig | None = None`. A helper `_match_poly_fixture(parsed, fixtures) -> Fixture | None` matching by league+name+date. `run()` loads `polymarket_markets.jsonl`, matches each market to a fixture by name, calls `build_rows`, and `attach_polymarket_row`s the result — counting stamped/dropped.

- [ ] **Step 1: Write the failing test**

Create `tests/mappers/test_polymarket_pipeline.py`:

```python
from mappers.pipeline import _match_poly_fixture


class _FX:
    def __init__(self, home_name, away_name, start_date):
        self.home_name = home_name
        self.away_name = away_name
        self.start_date = start_date


def test_match_poly_fixture_by_name_and_date():
    fixtures = [
        _FX("Arizona Diamondbacks", "St. Louis Cardinals", "2026-07-21T23:00:00Z"),
        _FX("Boston Red Sox", "New York Yankees", "2026-07-21T23:00:00Z"),
    ]
    parsed = {"team_a": "arizona diamondbacks", "team_b": "st louis cardinals",
              "date": "2026-07-21"}
    fx = _match_poly_fixture(parsed, fixtures)
    assert fx is fixtures[0]


def test_match_poly_fixture_none_when_no_name_match():
    fixtures = [_FX("Boston Red Sox", "New York Yankees", "2026-07-21T23:00:00Z")]
    parsed = {"team_a": "arizona diamondbacks", "team_b": "st louis cardinals",
              "date": "2026-07-21"}
    assert _match_poly_fixture(parsed, fixtures) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/mappers/test_polymarket_pipeline.py -q`
Expected: FAIL — `ImportError: cannot import name '_match_poly_fixture'`.

- [ ] **Step 3: Add `_match_poly_fixture` + the LeagueConfig field + the run() block**

In `mappers/pipeline.py`:

(a) add to the imports at the top (with the other `from mappers.exchanges import ...`):
```python
from mappers.exchanges import crypto_com, kalshi, optic, polymarket, px, runshop
```

(b) add the field to `LeagueConfig` (after `RUNSHOP`, ~line 58):
```python
    # Optional: only set for leagues with Polymarket combo-RFQ coverage.
    POLYMARKET: polymarket.PolymarketConfig | None = None
```

(c) add the matcher helper near `row_key` (~line 163):
```python
def _match_poly_fixture(parsed: dict, fixtures) -> "optic.Fixture | None":
    """Find the optic fixture for a parsed poly market by team-name + date (±0d).

    Name match uses polymarket._normalize/_names_equiv against the fixture's
    home_name/away_name (Polymarket has no team IDs). Both teams must match the
    fixture's two sides (in either orientation).
    """
    from mappers.exchanges.polymarket import _names_equiv, _normalize
    for fx in fixtures:
        if fx.start_date[:10] != parsed["date"]:
            continue
        hn, an = _normalize(fx.home_name), _normalize(fx.away_name)
        a, b = parsed["team_a"], parsed["team_b"]
        if (_names_equiv(a, hn) and _names_equiv(b, an)) or \
           (_names_equiv(a, an) and _names_equiv(b, hn)):
            return fx
    return None
```

(d) after the crypto build block (~line 1265, after the `crypto_superseded` print), add the poly pass. It runs AFTER the optic pass has populated `row_index` (guard #3 depends on that):
```python
    # === Polymarket: parse the bridge feed, match by name, stamp onto optic ===
    # Gated per-league (league.POLYMARKET). Poly rows merge onto existing optic
    # rows only (attach_polymarket_row) — a market optic didn't price is dropped.
    if league.POLYMARKET is not None:
        pcfg = league.POLYMARKET
        fixtures = [e.fixture for e in entries]
        pm_stamped = pm_dropped_no_optic = pm_no_fixture = pm_unparsed = 0
        for line in lines_if_exists(data_dir / "polymarket_markets.jsonl"):
            market = polymarket.parse_market(line)
            if market is None:
                continue
            if not market.slug.startswith(pcfg.slug_prefix + "-"):
                continue
            parsed = polymarket.parse_question(market.question, pcfg)
            if parsed is None:
                pm_unparsed += 1
                continue
            parsed["date"] = _poly_market_date(market.slug)
            if parsed["date"] is None:
                continue
            fx = _match_poly_fixture(parsed, fixtures)
            if fx is None:
                pm_no_fixture += 1
                continue
            rows = polymarket.build_rows(
                market, parsed, home=fx.home, away=fx.away,
                home_name=fx.home_name, away_name=fx.away_name,
                start_date=fx.start_date, cfg=pcfg, league=league.league)
            for pr in rows:
                if attach_polymarket_row(row_index, pr) == "stamped":
                    pm_stamped += 1
                else:
                    pm_dropped_no_optic += 1
        print(
            f"  polymarket [{league.league}]: {pm_stamped} stamped, "
            f"{pm_dropped_no_optic} dropped (optic didn't price), "
            f"{pm_no_fixture} no fixture, {pm_unparsed} non-game-line",
            file=sys.stderr)
```

(e) add the slug-date helper near `_match_poly_fixture`:
```python
_POLY_SLUG_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _poly_market_date(slug: str) -> str | None:
    """Extract the YYYY-MM-DD from a Polymarket single slug, or None."""
    m = _POLY_SLUG_DATE.search(slug or "")
    return m.group(1) if m else None
```
(ensure `import re` exists at the top of pipeline.py — it does; if not, add it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/mappers/test_polymarket_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full mappers test subset**

Run: `python -m pytest tests/mappers/test_polymarket.py tests/mappers/test_polymarket_attach.py tests/mappers/test_polymarket_pipeline.py -q`
Expected: PASS (all poly tests).

- [ ] **Step 6: Commit**

```bash
git add mappers/pipeline.py tests/mappers/test_polymarket_pipeline.py
git commit -m "feat(polymarket): pipeline wiring — LeagueConfig.POLYMARKET + name-match + attach pass"
```

---

### Task 6: `flatten_rows` constructed Polymarket block (passthrough PRESERVED)

**CORRECTED from the original plan:** do NOT remove `"Polymarket"` from `OPTIC_MAPPED_SPORTSBOOKS`. The passthrough is the existing source of every optic-already-mapped Polymarket row in `market_mapping` (incl. the ~152 tokens Wave 0's maker union relies on) and is asserted by existing tests (`test_flatten_rows.py:81-112`). Removing it would drop that coverage and only re-add the tiny matched subset. Instead, emit the constructed row ONLY when optic's own `source_ids` LACK a Polymarket entry for this row — that is exactly the new coverage the matcher adds, and it avoids a same-MERGE-key double-emit with the passthrough.

**Files:**
- Modify: `BigQuery/load_mappings.py` (`flatten_rows`, add the constructed block before the optic-passthrough loop ~line 410)
- Test: `tests/BigQuery/test_flatten_rows.py` (append)
- **Do NOT modify** `mappers/exchanges/optic.py` (`OPTIC_MAPPED_SPORTSBOOKS` stays as-is, Polymarket included).

**Interfaces:**
- Consumes: a nested mapping record with a `polymarket` block (from `canonical_row_to_json`, Task 1) and an `optic_odds` block (poly rows always merge onto optic → `o is not None`).
- Produces: `flatten_rows` yields `{**base, "sportsbook": "Polymarket", "source_ids": {"selection_id": <clob_token_id>}}` **only when `"Polymarket" not in optic_odds.source_ids`**. When optic already carries Polymarket source_ids, the existing passthrough loop emits it (unchanged) — the constructed block stays silent to avoid a duplicate same-key row.

- [ ] **Step 1: Write the failing tests**

Append to `tests/BigQuery/test_flatten_rows.py` (leave the existing passthrough tests untouched):

```python
def _mlb_total_rec(optic_source_ids):
    return {
        "key": {"league": "mlb", "start_date": "2026-07-21T23:00:00Z",
                "home": "AZ", "away": "STL", "market_type": "game_total",
                "line": 8.5, "side": "over", "grouping_key": None},
        "optic_odds": {"game_id": "g1", "fixture_id": "FX1", "market_id": "total_runs",
                       "selection": "", "selection_line": "over", "points": 8.5,
                       "grouping_key": "default", "source_ids": optic_source_ids},
        "polymarket": {"clob_token_id": "cO", "condition_id": "0xabc",
                        "position_id": "pO", "slug": "mlb-az-stl-2026-07-21",
                        "question": "AZ vs. STL: O/U 8.5"},
    }


def test_flatten_rows_emits_constructed_polymarket_when_optic_lacks_it():
    from BigQuery.load_mappings import flatten_rows
    # optic did NOT map this token -> the matcher's constructed row is the new coverage
    rows = list(flatten_rows(_mlb_total_rec({}), "2026-07-21T23:00:00Z"))
    poly = [r for r in rows if r["sportsbook"] == "Polymarket"]
    assert len(poly) == 1
    assert poly[0]["source_ids"] == {"selection_id": "cO"}
    assert poly[0]["fixture_id"] == "FX1" and poly[0]["market_id"] == "total_runs"


def test_flatten_rows_no_double_polymarket_when_optic_already_has_it():
    from BigQuery.load_mappings import flatten_rows
    # optic ALREADY maps this token -> passthrough emits it; constructed must stay silent
    # (a second same-MERGE-key row would collide). Exactly ONE Polymarket row, from passthrough.
    rows = list(flatten_rows(_mlb_total_rec({"Polymarket": {"selection_id": "cO"}}),
                             "2026-07-21T23:00:00Z"))
    poly = [r for r in rows if r["sportsbook"] == "Polymarket"]
    assert len(poly) == 1
    assert poly[0]["source_ids"] == {"selection_id": "cO"}  # from optic passthrough
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/BigQuery/test_flatten_rows.py -k polymarket -q`
Expected: `test_..._when_optic_lacks_it` FAILS (no constructed row yet — 0 Polymarket rows); `test_..._no_double...` passes already (passthrough emits the one row). Confirm the first is RED before implementing.

- [ ] **Step 3: Implement (one file)**

In `BigQuery/load_mappings.py`, `flatten_rows`, immediately BEFORE the optic-passthrough loop (`for sportsbook in OPTIC_MAPPED_SPORTSBOOKS:`, ~line 410) add:
```python
    # Constructed Polymarket row — ONLY for a token optic's own source_ids lack
    # (the coverage the matcher adds). When optic already carries Polymarket
    # source_ids, the passthrough loop below emits it; emitting a second row with
    # the same MERGE key here would collide, so stay silent. Poly rows always
    # merge onto an optic row (guard #3), so `base` is Optic-derived.
    pm = rec.get("polymarket")
    if pm is not None and o is not None and "Polymarket" not in (o.get("source_ids") or {}):
        yield {**base, "sportsbook": "Polymarket",
               "source_ids": {"selection_id": pm["clob_token_id"]}}
```
Do NOT touch `OPTIC_MAPPED_SPORTSBOOKS`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/BigQuery/test_flatten_rows.py -k polymarket -q`
Expected: PASS (both new tests).

- [ ] **Step 5: Run the full flatten_rows test file (regression: passthrough tests must still pass)**

Run: `.venv/bin/python -m pytest tests/BigQuery/test_flatten_rows.py -q`
Expected: PASS — existing passthrough tests (`test_flatten_rows.py:81-112`) still green (Polymarket still in the passthrough set), plus the 2 new ones.

- [ ] **Step 6: Commit**

```bash
git add BigQuery/load_mappings.py tests/BigQuery/test_flatten_rows.py
git commit -m "feat(polymarket): constructed Polymarket source_ids in flatten_rows (passthrough preserved, gated to optic-unmapped tokens only)"
```

---

### Task 7: `fetch/polymarket.py` — bridge → polymarket_markets.jsonl

**Files:**
- Create: `fetch/polymarket.py`
- Modify: `fetch/__main__.py` (add to `FETCHERS`, ~line 20)
- Test: `tests/fetch/test_polymarket.py` (create)

**Interfaces:**
- Consumes: the BQ bridge table `raw_ingestion_us.polymarket_position_token_bridge` (via `BigQuery.polymarket_bq_util.bq_client`).
- Produces: `build_market_lines(rows) -> list[dict]` grouping bridge rows by `condition_id` into `{condition_id, slug, question, outcomes:[{clob_token_id, position_id, outcome_label, outcome_index}]}`; a `main()` writing `<out-dir>/polymarket_markets.jsonl` (mirrors `fetch/crypto_com.py`). `"fetch.polymarket"` added to `FETCHERS`.

- [ ] **Step 1: Write the failing test**

Create `tests/fetch/test_polymarket.py`:

```python
from fetch.polymarket import build_market_lines


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_build_market_lines_groups_by_condition_id():
    rows = [
        _Row(condition_id="0xA", slug="mlb-az-stl-2026-07-21", question="AZ vs. STL",
             clob_token_id="cA0", position_id="pA0", outcome_label="Arizona Diamondbacks", outcome_index=0),
        _Row(condition_id="0xA", slug="mlb-az-stl-2026-07-21", question="AZ vs. STL",
             clob_token_id="cA1", position_id="pA1", outcome_label="St. Louis Cardinals", outcome_index=1),
        _Row(condition_id="0xB", slug="mlb-bos-nyy-2026-07-21", question="BOS vs. NYY: O/U 8.5",
             clob_token_id="cB0", position_id="pB0", outcome_label="Over", outcome_index=0),
    ]
    out = build_market_lines(rows)
    by_cid = {m["condition_id"]: m for m in out}
    assert set(by_cid) == {"0xA", "0xB"}
    assert by_cid["0xA"]["question"] == "AZ vs. STL"
    assert len(by_cid["0xA"]["outcomes"]) == 2
    # outcomes ordered by outcome_index
    assert [o["outcome_index"] for o in by_cid["0xA"]["outcomes"]] == [0, 1]
    assert by_cid["0xA"]["outcomes"][0]["clob_token_id"] == "cA0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/fetch/test_polymarket.py -q`
Expected: FAIL — `ModuleNotFoundError: fetch.polymarket`.

- [ ] **Step 3: Create the fetcher**

Create `fetch/polymarket.py`:

```python
"""Fetch the Polymarket position↔token bridge → polymarket_markets.jsonl.

The bridge (raw_ingestion_us.polymarket_position_token_bridge) already carries,
per clob_token_id, the single market's slug/question + outcome_label. This
fetcher reads the current (latest last_updated) bridge rows and groups them by
condition_id into one market-per-line for the mapper's Polymarket matcher —
mirroring fetch/crypto_com.py's flat-JSONL contract. No live API calls (the
bridge loader already did the combos-rfq/Gamma fetch).
"""

import argparse
import json
import os
import sys

from BigQuery.polymarket_bq_util import bq_client, qualify

BRIDGE_TABLE = "raw_ingestion_us.polymarket_position_token_bridge"


def build_market_lines(rows) -> list[dict]:
    """Group bridge rows by condition_id into one market dict each.

    Outcomes are sorted by outcome_index so index-aligned consumers stay stable.
    """
    by_cid: dict[str, dict] = {}
    for r in rows:
        m = by_cid.setdefault(str(r.condition_id), {
            "condition_id": str(r.condition_id),
            "slug": r.slug or "",
            "question": r.question or "",
            "outcomes": [],
        })
        m["outcomes"].append({
            "clob_token_id": str(r.clob_token_id),
            "position_id": str(r.position_id),
            "outcome_label": r.outcome_label or "",
            "outcome_index": int(r.outcome_index) if r.outcome_index is not None else 0,
        })
    for m in by_cid.values():
        m["outcomes"].sort(key=lambda o: o["outcome_index"])
    return list(by_cid.values())


def _fetch_rows(client):
    table = qualify(client, BRIDGE_TABLE)
    q = f"""
      SELECT condition_id, slug, question, clob_token_id, position_id,
             outcome_label, outcome_index
      FROM `{table}`
      WHERE DATE(last_updated) = CURRENT_DATE()
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY clob_token_id ORDER BY last_updated DESC) = 1
    """
    return list(client.query(q).result())


def main():
    p = argparse.ArgumentParser(description="Fetch Polymarket bridge -> jsonl.")
    p.add_argument("--out-dir", help="Directory to write polymarket_markets.jsonl into.")
    p.add_argument("--out", help="Explicit output path (ad-hoc).")
    p.add_argument("--league", nargs="*", default=[], help="Ignored; bridge is league-agnostic.")
    p.add_argument("--max-items", type=int, default=None, help="Cap markets (smoke test).")
    args = p.parse_args()

    client = bq_client()
    markets = build_market_lines(_fetch_rows(client))
    if args.max_items:
        markets = markets[: args.max_items]

    out_path = None
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        out_path = os.path.join(args.out_dir, "polymarket_markets.jsonl")
    elif args.out:
        out_path = args.out

    if out_path:
        with open(out_path, "w") as f:
            for m in markets:
                print(json.dumps(m), file=f)
        print(f"Wrote {out_path} ({len(markets)} markets)", file=sys.stderr)
    else:
        for m in markets:
            print(json.dumps(m))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Register in the fetch orchestrator**

In `fetch/__main__.py`, add `"fetch.polymarket"` to `FETCHERS`:
```python
FETCHERS = [
    "fetch.optic",
    "fetch.kalshi",
    "fetch.px",
    "fetch.crypto_com",
    "fetch.polymarket",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/fetch/test_polymarket.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add fetch/polymarket.py fetch/__main__.py tests/fetch/test_polymarket.py
git commit -m "feat(polymarket): fetch bridge -> polymarket_markets.jsonl; register fetcher"
```

---

### Task 8: mlb `POLYMARKET` config + integration test

**Files:**
- Modify: `mappers/leagues/mlb.py` (add `POLYMARKET=` to `LEAGUE`, import `PolymarketConfig`)
- Test: `tests/mappers/test_polymarket_mlb_integration.py` (create)

**Interfaces:**
- Consumes: `PolymarketConfig` (Task 2); the mlb `LeagueConfig`.
- Produces: `mlb.LEAGUE.POLYMARKET` set to an mlb `PolymarketConfig` (`slug_prefix="mlb"`, `optic_league_id="mlb"`, `market_types={"moneyline": MONEYLINE, "total": GAME_TOTAL}`). An integration test proving parse→match→build→attach end to end for one moneyline and one total market against a synthetic optic `row_index`.

- [ ] **Step 1: Write the failing test**

Create `tests/mappers/test_polymarket_mlb_integration.py`:

```python
from mappers.leagues import mlb
from mappers.exchanges import polymarket as pm
from mappers.pipeline import attach_polymarket_row, row_key, _match_poly_fixture
from mappers.shared import CanonicalRow


def test_mlb_polymarket_config_present():
    assert mlb.LEAGUE.POLYMARKET is not None
    assert mlb.LEAGUE.POLYMARKET.slug_prefix == "mlb"
    assert mlb.LEAGUE.POLYMARKET.market_types["total"].value == "game_total"


class _FX:
    home, away = "AZ", "STL"
    home_name, away_name = "Arizona Diamondbacks", "St. Louis Cardinals"
    start_date = "2026-07-21T23:00:00Z"


def test_mlb_total_end_to_end_stamps_optic_row():
    cfg = mlb.LEAGUE.POLYMARKET
    # optic already priced the total -> row exists in the index
    optic_over = CanonicalRow(league="mlb", start_date=_FX.start_date, home="AZ",
                              away="STL", market_type="game_total", line=8.5,
                              side="over", optic_id="OPT_OVER")
    index = {row_key(optic_over): optic_over}

    market = pm.PolyMarket(condition_id="0xB", slug="mlb-az-stl-2026-07-21",
        question="Arizona Diamondbacks vs. St. Louis Cardinals: O/U 8.5",
        outcomes=[pm.PolyOutcome(clob_token_id="cO", position_id="pO",
                                 outcome_label="Over", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="cU", position_id="pU",
                                 outcome_label="Under", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg)
    parsed["date"] = "2026-07-21"
    fx = _match_poly_fixture(parsed, [_FX()])
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="mlb")
    results = [attach_polymarket_row(index, r) for r in rows]
    # over stamps onto the optic row; under has no optic row -> dropped (guard #3)
    assert "stamped" in results and "dropped_no_optic" in results
    assert index[row_key(optic_over)].polymarket_clob_token_id == "cO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/mappers/test_polymarket_mlb_integration.py -q`
Expected: FAIL — `AttributeError: ... POLYMARKET is None` (or attribute missing).

- [ ] **Step 3: Add the mlb POLYMARKET config**

In `mappers/leagues/mlb.py`:

(a) add the import (with the other exchange imports):
```python
from mappers.exchanges.polymarket import PolymarketConfig
```

(b) add the config constant (after `OPTIC = OpticConfig(...)`):
```python
POLYMARKET = PolymarketConfig(
    slug_prefix="mlb",
    optic_league_id="mlb",
    market_types={
        "moneyline": MarketType.MONEYLINE,
        "total": MarketType.GAME_TOTAL,
    },
)
```

(c) pass it into `LEAGUE`:
```python
LEAGUE = LeagueConfig(
    league=League.MLB,
    KALSHI=KALSHI, PX=PX, OPTIC=OPTIC, POLYMARKET=POLYMARKET,
    OUTPUT_ORDER=OUTPUT_ORDER, MarketType=MarketType,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/mappers/test_polymarket_mlb_integration.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole poly + flatten test set**

Run: `python -m pytest tests/mappers/test_polymarket.py tests/mappers/test_polymarket_attach.py tests/mappers/test_polymarket_pipeline.py tests/mappers/test_polymarket_mlb_integration.py tests/BigQuery/test_flatten_rows.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mappers/leagues/mlb.py tests/mappers/test_polymarket_mlb_integration.py
git commit -m "feat(polymarket): wire mlb POLYMARKET config + end-to-end integration test"
```

---

## Verification (post-implementation, before deploy)

- [ ] Run the fetcher against test BQ and eyeball the jsonl:
  `python -m fetch.polymarket --out /tmp/pm.jsonl && head -3 /tmp/pm.jsonl` (expect grouped-by-condition markets with mlb entries).
- [ ] Run a full mlb mapping pass (`python -m mappers.run --league mlb --write-mappings ...`) and read the `polymarket [mlb]: N stamped, M dropped ...` log line — expect `N` in the low hundreds (the ~306 recoverable estimate), `M` large (F5/props dropped by guard #3, correct).
- [ ] Load into TEST `markets_us.market_mapping`, then re-run the maker's bridge-vs-market_mapping coverage harness — confirm mlb mapped-token count rose.
- [ ] **Side-correctness audit (Norway gate):** sample ~20 stamped mlb rows and confirm, against the live optic odd, that `over`/`under` and each moneyline team side match the Polymarket outcome label. A wrong side blocks the wave.

## Self-review

- **Spec coverage:** Tasks 1-8 implement the mmmapper §"Components" table for mlb (fetch, matcher module, CanonicalRow fields, pipeline wiring, flatten_rows, mlb config, tests) + flip-safety guards #1-#3 (§"Flip-safety guards": label-bound side = Task 3; complementary-pair drop = Task 3; market-must-exist-in-optic = Task 4 attach). Guard #4 (cross-check where optic already maps the clob) was deferred during Wave 1 and then **implemented immediately after (commit f4db57d)** as the tennis prerequisite — see the note below. Run line / other leagues are explicitly out of Wave 1 scope (Global Constraints).
- **Placeholders:** none — every code step has complete code.
- **Type consistency:** `PolyMarket`/`PolyOutcome`/`PolymarketConfig` fields, `build_rows` signature, `attach_polymarket_row(row_index, pr) -> str` return values (`"stamped"`/`"dropped_no_optic"`), and the `polymarket_*` CanonicalRow field names are used identically across Tasks 1-8. `_match_poly_fixture` and `_poly_market_date` are defined in Task 5 and consumed by Task 5/8 only.
- **Guard #4 — history + resolution:** during Wave 1 the plan wrongly claimed guard #4 was "satisfied structurally" by attach-onto-optic; the whole-branch review corrected that (attach + the per-row flatten gate do NOT catch the case where optic maps *our* token to the opposite side while leaving the other side unmapped → conflicting duplicate). It was then **implemented (commit f4db57d)** as the prerequisite before the ambiguous-label tennis wave: `pipeline._build_optic_poly_index` builds a global `{clob → optic row_key}`; the poly pass constructs only *novel* tokens, skips *agrees*, and drops+logs *conflicts*. The pre-live side-correctness audit remains a deploy gate (defence in depth), but the guard is no longer absent.
