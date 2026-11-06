> Historical. Tip/console references are retired; see CLAUDE.md.

# Wave 2 — tennis (atp/wta) Polymarket matcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** map Polymarket tennis **match-winner** tokens (atp/wta) to OpticOdds moneyline — reusing the Wave-1 matcher + guard #4 — by teaching the parser the tournament-prefixed form `"<Tournament>: <Player A> vs <Player B>"` and matching players by strict `normalize_player_name` equality. ~154 recoverable tokens (116 atp + 38 wta).

**Architecture:** Optic prices tennis **moneyline only**, so match-winner is the only recoverable market (totals/sets auto-drop via guard #3). Add a `question_style` flag to `PolymarketConfig`: `"mlb_suffix"` (default, unchanged mlb behavior) vs `"tennis_prefix"`. Route name normalization/comparison through two style-gated helpers so mlb (team names, containment) is byte-identical while tennis uses player-name normalization + **exact** equality (safer for short surnames). Guard #4 (already built) protects the optic-already-mapped tennis tokens; strict player matching protects the novel ones.

**Tech Stack:** mmmapper; `.venv/bin/python -m pytest`; ruff.

## Global Constraints
- **mlb behavior MUST be unchanged.** `question_style` defaults to `"mlb_suffix"`; every mlb code path keeps the current `_normalize` + `_names_equiv` (containment). Full `tests/mappers/` suite must stay green (≈313 passed).
- Tennis maps **match-winner only** (`market_types={"moneyline": MarketType.MONEYLINE}`). Totals/sets/doubles/"Completed Match" must parse to None (they'd drop at guard #3 anyway, but reject early).
- Player matching for tennis = `normalize_player_name(label) == normalize_player_name(fixture_name)` — **exact**, never containment.
- Poly tennis question form: `"<Tournament>: <Player A> vs <Player B>"`; `outcome_label` = full player name; bridge slug prefix = `atp` / `wta`.
- Do NOT weaken guard #1-#4 or touch `attach_polymarket_row`/flatten.

---

### Task 1: `question_style` + style-gated name helpers + tennis parse/match

**Files:**
- Modify: `mappers/exchanges/polymarket.py` (`PolymarketConfig`, `parse_question`, `build_rows`, add `normalize_player_name` import + helpers)
- Modify: `mappers/pipeline.py` (`_match_poly_fixture` — thread `cfg`/style + use the helper)
- Test: `tests/mappers/test_polymarket.py` + `tests/mappers/test_polymarket_pipeline.py`

**Interfaces:**
- Produces: `PolymarketConfig.question_style: str = "mlb_suffix"`; helpers `_norm_name(s, style)` and `_name_match(a, b, style)`; `parse_question` handles `"tennis_prefix"`; `_match_poly_fixture(parsed, fixtures, style)` gains the style arg.

- [ ] **Step 1: failing tests** — append to `tests/mappers/test_polymarket.py`:

```python
TENNIS_CFG = pm.PolymarketConfig(
    slug_prefix="atp", optic_league_id="atp",
    market_types={"moneyline": MarketType.MONEYLINE},
    question_style="tennis_prefix",
)


def test_parse_question_tennis_match_winner():
    out = pm.parse_question("Bloomfield Hills: Alex Michelsen vs Aidan Mayo", TENNIS_CFG)
    assert out["market_kind"] == "moneyline"
    assert out["team_a"] == pm._norm_name("Alex Michelsen", "tennis_prefix")
    assert out["team_b"] == pm._norm_name("Aidan Mayo", "tennis_prefix")


def test_parse_question_tennis_strips_multicolon_and_periods():
    out = pm.parse_question("ATP 250: Bloomfield Hills: J.J. Wolf vs Coleman Wong", TENNIS_CFG)
    assert out["market_kind"] == "moneyline"
    assert out["team_a"] == pm._norm_name("J.J. Wolf", "tennis_prefix")  # -> "jj_wolf"


def test_parse_question_tennis_rejects_totals_doubles_completed():
    for q in ["Added vs. Bax: Match O/U 21.5",
              "Adolfo Vallejo vs Kilian Feldbausch: Total Sets O/U 2.5",
              "Bloomfield Hills: Lammons/Withrow vs Galarneau/Tomic",
              "Completed Match: Oskari Paldanius vs Franco Roncadelli"]:
        assert pm.parse_question(q, TENNIS_CFG) is None


def test_name_match_tennis_exact_not_containment():
    # containment would wrongly equate "Rune" with "Holger Rune"; exact must not
    assert pm._name_match(pm._norm_name("Holger Rune", "tennis_prefix"),
                          pm._norm_name("Holger Rune", "tennis_prefix"), "tennis_prefix")
    assert not pm._name_match(pm._norm_name("Rune", "tennis_prefix"),
                              pm._norm_name("Holger Rune", "tennis_prefix"), "tennis_prefix")


def test_mlb_style_unchanged_containment():
    # mlb_suffix keeps containment behavior
    assert pm._name_match("arizona diamondbacks", "arizona diamondbacks", "mlb_suffix")
    assert pm._name_match("arizona", "arizona diamondbacks", "mlb_suffix")  # containment ok for teams
```

- [ ] **Step 2: RED** — `.venv/bin/python -m pytest tests/mappers/test_polymarket.py -k "tennis or name_match or mlb_style" -q` → fails (`_norm_name`/`_name_match`/`question_style` missing).

- [ ] **Step 3: implement** in `mappers/exchanges/polymarket.py`:

Add import: `from mappers.shared import CanonicalRow, normalize_player_name`.

Add the field to `PolymarketConfig` (defaulted — mlb untouched):
```python
    question_style: str = "mlb_suffix"  # "mlb_suffix" (A vs B[: O/U N]) | "tennis_prefix" (<Tournament>: A vs B)
```

Add the helpers (after `_names_equiv`):
```python
def _norm_name(s: str | None, style: str) -> str:
    """Normalize a team/player name per league style.

    tennis_prefix -> normalize_player_name (diacritic + base-letter fold, period +
    Jr/Sr strip, underscore-joined) so a poly player label agrees with the Optic
    entity. mlb_suffix -> the team _normalize (space-joined, NFKD only).
    """
    if style == "tennis_prefix":
        return normalize_player_name(s or "")
    return _normalize(s)


def _name_match(a: str, b: str, style: str) -> bool:
    """Compare two already-_norm_name'd names per style.

    tennis_prefix -> EXACT equality (never containment: "rune" must not match
    "holger_rune"). mlb_suffix -> the team containment check (_names_equiv-style).
    """
    if not a or not b:
        return False
    if style == "tennis_prefix":
        return a == b
    return a == b or a in b or b in a
```

Rewrite `parse_question` to branch on `cfg.question_style` and use `_norm_name`:
```python
def parse_question(question: str, cfg: PolymarketConfig) -> dict | None:
    q = (question or "").strip()
    style = cfg.question_style
    if style == "tennis_prefix":
        # "<Tournament>: <Player A> vs <Player B>" — players after the LAST colon.
        # Reject doubles (slash), settled ("Completed"), and totals/sets (O/U etc.).
        if "/" in q or re.search(r"(?i)\bcompleted\b", q):
            return None
        players = q.rsplit(":", 1)[-1].strip() if ":" in q else q
        if re.search(r"(?i)o/u|total|\bsets?\b|games", players):
            return None
        m = _Q_MONEYLINE.match(players)
        if not m:
            return None
        return {"market_kind": "moneyline",
                "team_a": _norm_name(m.group(1), style),
                "team_b": _norm_name(m.group(2), style), "line": None}
    # default mlb_suffix
    mt = _Q_TOTAL.match(q)
    if mt:
        try:
            line = float(mt.group(3))
        except ValueError:
            return None
        return {"market_kind": "total", "team_a": _norm_name(mt.group(1), style),
                "team_b": _norm_name(mt.group(2), style), "line": line}
    if ":" in q:
        return None
    mm = _Q_MONEYLINE.match(q)
    if mm:
        return {"market_kind": "moneyline", "team_a": _norm_name(mm.group(1), style),
                "team_b": _norm_name(mm.group(2), style), "line": None}
    return None
```

In `build_rows`, the moneyline branch must compare label→fixture side via `_name_match`/`_norm_name` using `cfg.question_style` (replace the current `_names_equiv(_normalize(...), _normalize(...))`):
```python
    style = cfg.question_style
    ...
    if kind == "moneyline":
        seen_sides: set[str] = set()
        for o in market.outcomes:
            lab = _norm_name(o.outcome_label, style)
            if _name_match(lab, _norm_name(home_name, style), style):
                side = home
            elif _name_match(lab, _norm_name(away_name, style), style):
                side = away
            else:
                return []
            ...
```
(The `total` branch is mlb-only; leave it. Keep the `len(outcomes) != 2` guard + complementary-pair checks unchanged.)

- [ ] **Step 4: thread style into `_match_poly_fixture`** — `mappers/pipeline.py`:
Change signature to `_match_poly_fixture(parsed, fixtures, style)` and use the helpers:
```python
def _match_poly_fixture(parsed: dict, fixtures, style: str) -> "optic.Fixture | None":
    from mappers.exchanges.polymarket import _name_match, _norm_name
    a, b = parsed["team_a"], parsed["team_b"]   # already _norm_name'd by parse_question
    target = parsed["date"]
    fallback = None
    for fx in fixtures:
        hn, an = _norm_name(fx.home_name, style), _norm_name(fx.away_name, style)
        names_ok = (_name_match(a, hn, style) and _name_match(b, an, style)) or \
                   (_name_match(a, an, style) and _name_match(b, hn, style))
        if not names_ok:
            continue
        if fx.start_date[:10] == target:
            return fx
        if fallback is None and _within_one_day(fx.start_date, target):
            fallback = fx
    return fallback
```
Update its one call site in the poly pass to pass `pcfg.question_style`.
Add a pipeline test (`tests/mappers/test_polymarket_pipeline.py`): a tennis fixture (`home_name="Alex Michelsen"`, `away_name="Aidan Mayo"`) matched from `parse_question("Bloomfield Hills: Alex Michelsen vs Aidan Mayo", TENNIS_CFG)` (with `parsed["date"]` set) returns that fixture; and a wrong-player fixture does not.

- [ ] **Step 5: GREEN + regression** — `.venv/bin/python -m pytest tests/mappers/test_polymarket.py tests/mappers/test_polymarket_pipeline.py -q`, then FULL `.venv/bin/python -m pytest tests/mappers/ -q` (mlb + all leagues unchanged, ≈313 passed). ruff --fix.

- [ ] **Step 6: commit** `feat(polymarket): tennis_prefix question style + player-name-exact matching (mlb path unchanged)`.

---

### Task 2: atp/wta `POLYMARKET` config + integration

**Files:**
- Modify: `mappers/leagues/atp.py`, `mappers/leagues/wta.py`
- Test: `tests/mappers/test_polymarket_tennis_integration.py` (create)

**Interfaces:** `atp.LEAGUE.POLYMARKET` / `wta.LEAGUE.POLYMARKET` set with `question_style="tennis_prefix"`, `market_types={"moneyline": MONEYLINE}`.

- [ ] **Step 1: failing integration test** — create `tests/mappers/test_polymarket_tennis_integration.py`:

```python
from mappers.leagues import atp, wta
from mappers.exchanges import polymarket as pm
from mappers.pipeline import attach_polymarket_row, row_key, _match_poly_fixture
from mappers.shared import CanonicalRow


def test_atp_wta_polymarket_config():
    for lg in (atp.LEAGUE, wta.LEAGUE):
        assert lg.POLYMARKET is not None
        assert lg.POLYMARKET.question_style == "tennis_prefix"
        assert lg.POLYMARKET.market_types == {"moneyline": pm.MarketType.MONEYLINE}


class _FX:
    home, away = "MIC", "MAY"
    home_name, away_name = "Alex Michelsen", "Aidan Mayo"
    start_date = "2026-07-22T18:00:00Z"


def test_atp_match_winner_end_to_end_stamps_optic_row():
    cfg = atp.LEAGUE.POLYMARKET
    # optic priced the match-winner (moneyline) for player MIC
    optic_mic = CanonicalRow(league="atp", start_date=_FX.start_date, home="MIC",
                             away="MAY", market_type="moneyline", side="MIC", optic_id="O1")
    index = {row_key(optic_mic): optic_mic}
    market = pm.PolyMarket(condition_id="0xT", slug="atp-bloomfield-2026-07-22",
        question="Bloomfield Hills: Alex Michelsen vs Aidan Mayo",
        outcomes=[pm.PolyOutcome(clob_token_id="cM", position_id="pM",
                                 outcome_label="Alex Michelsen", outcome_index=0),
                  pm.PolyOutcome(clob_token_id="cY", position_id="pY",
                                 outcome_label="Aidan Mayo", outcome_index=1)])
    parsed = pm.parse_question(market.question, cfg); parsed["date"] = "2026-07-22"
    fx = _match_poly_fixture(parsed, [_FX()], cfg.question_style)
    assert fx is not None
    rows = pm.build_rows(market, parsed, home=fx.home, away=fx.away,
                         home_name=fx.home_name, away_name=fx.away_name,
                         start_date=fx.start_date, cfg=cfg, league="atp")
    results = [attach_polymarket_row(index, r) for r in rows]
    assert "stamped" in results  # MIC side stamps onto the optic moneyline row
    assert index[row_key(optic_mic)].polymarket_clob_token_id == "cM"
```

- [ ] **Step 2: RED** — `.venv/bin/python -m pytest tests/mappers/test_polymarket_tennis_integration.py -q` → `POLYMARKET is None`.

- [ ] **Step 3: implement** — in `mappers/leagues/atp.py`: `from mappers.exchanges.polymarket import PolymarketConfig`, add
```python
POLYMARKET = PolymarketConfig(
    slug_prefix="atp", optic_league_id="atp",
    market_types={"moneyline": MarketType.MONEYLINE},
    question_style="tennis_prefix",
)
```
and add `POLYMARKET=POLYMARKET` to `LEAGUE = LeagueConfig(...)`. Same for `wta.py` with `slug_prefix="wta"`, `optic_league_id="wta"`.

- [ ] **Step 4: GREEN + regression** — target test, then FULL `tests/mappers/ -q` (atp/wta existing kalshi/optic mapping unaffected — no `polymarket_markets.jsonl` in fixtures → poly pass no-op). ruff --fix.

- [ ] **Step 5: commit** `feat(polymarket): enable tennis matcher for atp + wta (match-winner)`.

## Self-review
- Spec coverage: tennis match-winner parse (tournament-prefix) + strict player matching + atp/wta configs + guard-#4/#3 reused. mlb untouched (style default + gated helpers).
- No placeholders. Type consistency: `question_style` on config; `_norm_name(s,style)`/`_name_match(a,b,style)` used identically in parse/match/build; `_match_poly_fixture` gains `style` and its call site passes `pcfg.question_style`.
