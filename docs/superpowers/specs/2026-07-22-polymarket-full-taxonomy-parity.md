> Historical. Tip/console references are retired; see CLAUDE.md.

# Polymarket→OpticOdds Matcher — Full-Taxonomy Parity Design

**Date:** 2026-07-22
**Supersedes/extends:** `2026-07-21-polymarket-optic-matcher-design.md` (Waves 1–2: MLB moneyline+total, tennis moneyline).
**Branch:** `feat/polymarket-optic-matcher` (mmmapper).

## Goal

Bring the Polymarket active matcher to **exact parity** with the crypto.com and Kalshi mappers: dispatch on `(Scope, Shape)` and emit CanonicalRows across the **full market taxonomy** optic prices — game lines, spreads, totals, three-way, team totals, game props, and **player props** — not the moneyline+total subset shipped in Waves 1–2. Every optic-priced market that Polymarket RFQs must be mappable.

## Guiding constraints (unchanged from Waves 1–2)

- **Optic-gated, stamp-else-drop.** A Polymarket row only ever *stamps onto an existing optic-backed `row_key` entry* (`attach_polymarket_row`); no optic row ⇒ dropped. So `(market_type, entity, line, side)` correctness is the whole game.
- **Flip-safety is money-critical** (prior Norway over/under arb incident). The four guards hold and extend to every new shape:
  - **#1** side bound to the outcome_label / the entity named in the question — never positional index.
  - **#2** complementary-pair / arity drop — a market that doesn't cleanly resolve its sides is dropped whole.
  - **#3** market must exist in optic for this fixture (`attach_polymarket_row`).
  - **#4** cross-check parsed `row_key` against optic's own `source_ids["Polymarket"]` clobTokenId (`_build_optic_poly_index`) — disagreement drops the token.
- **Bridge-driven.** Input is the position↔token bridge's natural-language `question` + `outcome_label`s per `clob_token_id`. Team/player identity resolved by NAME against the optic schedule (Polymarket has no stable IDs) — `normalize_player_name` for players (the same merge-key function optic/kalshi/crypto use), team-name matching for teams.

## Scope (optic-gated, measured 2026-07-22 on marketmaking-test)

Optic prices ~9 leagues from independent books; only their intersection with Polymarket RFQ volume is in scope. Per-league coverage matrix — **✅ done**, **➕ add**, **➖ out (not optic-priced or not RFQ'd)**:

| League (optic) | bridge pfx | moneyline | spread | game_total | team_total | 1H total | BTTS | corners | player props | 3-way ML |
|---|---|---|---|---|---|---|---|---|---|---|
| MLB | mlb | ✅ | ➕ run_line | ✅ | ➕ | ➕ 1st-inn | — | — | ➕ HR/K/Hits/Bases | — |
| MLS / Liga MX / UCL | mls/mex/ucl | — (3-way only) | ➕ asian_hcap | ➕ | ➕ | ➕ | ➕ | ➕ | ➕ anytime-scorer | ➕ |
| WNBA | wnba | ➕ | ➕ | ➕ | ➖ not priced | — | — | — | ➖ not optic-priced | — |
| UFC (MMA) | ufc | ➕ | — | ➕ total_rounds | — | — | — | — | — | — |
| ATP / WTA | atp/wta | ✅ | ➖ not priced | ➖ not priced | — | — | — | — | — | — |

**UFC extras** (all optic-priced): `total_rounds`, `go_the_distance`, `method_of_victory`, `round_betting`.
**Out of scope** (not optic-priced or unmappable): WNBA player props; tennis set/game totals; soccer correct-score / "any other score" / halftime-lead / to-score-first / 2H-winner props; MLB "tied after N innings".

## Architecture

Generalize `mappers/exchanges/polymarket.py` from a 2-kind hand-rolled parser to a **config-driven, (Scope,Shape)-dispatched** matcher mirroring crypto.com.

### 1. `PolymarketConfig` — per-league parse rules (mirrors `CryptoConfig.contract_types` / `prop_contract_types`)

```python
@dataclass(frozen=True)
class PolymarketConfig:
    slug_prefix: str
    optic_league_id: str
    question_style: Literal["mlb_suffix", "tennis_prefix"] = "mlb_suffix"   # existing (team-name matching mode)
    # market-type rules: an ORDERED list of (matcher, MarketType) parse rules.
    # Each matcher inspects (question, outcome_labels) and yields a structured
    # ParsedMarket or None. First rule that matches wins; None from all ⇒ drop.
    market_rules: tuple[MarketRule, ...] = ()
    player_aliases: Mapping[str, str] = field(default_factory=dict)  # poly spelling → optic normalized, when they diverge
```

A **`MarketRule`** binds a question-form recognizer to a `MarketType` and a side/line/entity extraction. Rules are small, declarative, and per-league-composed (a soccer league lists the soccer rules; MLB lists the baseball rules). This keeps the shared parser sport-agnostic and each league's vocabulary in its own module — exactly how crypto.com's `contract_types` dicts localize the feed vocabulary.

### 2. `parse_question` → `ParsedMarket`

Replace the current `{market_kind, team_a, team_b, line}` dict with a richer structured result carrying everything a row needs:

```python
@dataclass
class ParsedMarket:
    market_type: MarketType          # resolved canonical type
    team_a: str | None               # normalized, for fixture matching (game/team markets)
    team_b: str | None
    entity: str | None               # normalize_player_name(player) for PLAYER scope; team abbrev for TEAM yes/no; None for GAME
    line: float | None               # threshold (unsigned) or signed spread; None for moneyline/3way/yes-no
    date: str | None                 # match date parsed from question where present (e.g. "Will X win on YYYY-MM-DD?")
    label_to_side: Callable[[str], str | None]   # maps each outcome_label → canonical side, or None ⇒ drop market
```

`label_to_side` is the flip-safety core: for each Polymarket outcome, its label decides the side (guard #1). Per shape:
- **MONEYLINE / SPREAD** (team): label is a team name → side = matched fixture abbrev; signed line for spread.
- **THREE_WAY**: for `"Will <Team> win…?"` the affirmative (Yes) label → side = that team's abbrev; for `"…end in a draw?"` Yes → `_TIE`. No-labels → None (dropped — no 3-way counterpart, like Kalshi negatives).
- **TOTAL / OVER_UNDER** (game/team/player): Over→"over", Under→"under"; for Yes/No-at-threshold props, Yes→"over", No→"under" (the crypto/kalshi convention — optic never uses the `_YN` types).
- **YES_NO** (BTTS game-scoped; anytime-scorer player-scoped over-only): Yes→"yes"/"over", No→"no"/"under" as the type dictates.

### 3. `build_rows` → shape dispatch (mirrors crypto.com `_resolve_side` / `_player_prop_row` / `_game_prop_row`)

```python
def build_rows(market, parsed, *, home, away, home_name, away_name, start_date, cfg, league):
    shape = parsed.market_type.shape
    scope = parsed.market_type.scope
    # emit one CanonicalRow per outcome; side via parsed.label_to_side(label)
    # entity: PLAYER→parsed.entity (aliased+normalized); TEAM yes/no→team abbrev; GAME→None
    # line:   per parsed.line (signed for SPREAD)
    # arity/complementary guards per shape (guard #2)
```

Row stamp fields unchanged (`polymarket_clob_token_id/condition_id/position_id/slug/question`). Merge key produced must exactly equal optic's `row_key` for that market (§5 of the parity reference): `(league, start_date, home, away, market_type, entity, normalize_line(line), side, grouping_key=None)`.

### 4. New shared `MarketType`s (additive — safe for other mappers)

**MLB player props** (optic `market_id`s): `PLAYER_HOME_RUNS` (`player_home_runs`), `PLAYER_STRIKEOUTS` (`player_strikeouts`), `PLAYER_HITS` (`player_hits`), `PLAYER_BASES` (`player_bases`), `PLAYER_HITS_RUNS_RBIS` (`player_hits_+_runs_+_rbis`) — all `Scope.PLAYER, Shape.OVER_UNDER`. Baseball spread: reuse `POINT_SPREAD` (optic `run_line`). MLB 1st-inning total: `FIRST_INNING_TOTAL` (or map to existing period-total convention).

**MMA/UFC**: new `Sport.MMA` + `League.UFC`. New types: `TOTAL_ROUNDS` (`Scope.GAME, Shape.TOTAL`), `GO_THE_DISTANCE` (`Scope.GAME, Shape.YES_NO`), `METHOD_OF_VICTORY` (per-fighter yes/no — likely `Scope.PLAYER/Shape.YES_NO` keyed on fighter + method; TBD vs optic's "Method of Victory" selection encoding during Phase 4 planning), `ROUND_BETTING` (TBD). UFC moneyline = existing `MONEYLINE` (fighter = team abbrev via the tennis_prefix name-matching path).

### 5. New league modules + `LeagueConfig` change

- Add `League.WNBA` (`Sport.BASKETBALL`), `League.MLS`/`League.LIGA_MX`/`League.UCL` (`Sport.SOCCER`), `League.UFC` (`Sport.MMA`) to `leagues/__init__.py`; new modules under `mappers/leagues/`.
- Soccer/WNBA/UFC leagues here have **no Kalshi feed** → make `LeagueConfig.KALSHI: KalshiConfig | None = None` (currently required). Verify the pipeline's kalshi pass is already guarded on `cfg.KALSHI is not None` (it is for PX/CRYPTO); add the same guard for KALSHI if absent.
- Each new module supplies an `OpticConfig` (mirroring world_cup for soccer, nba for basketball) and a `POLYMARKET = PolymarketConfig(...)` with its `market_rules`.

## Flip-safety additions specific to new shapes

- **Player props**: entity MUST resolve via `normalize_player_name` (+ per-league `player_aliases` when poly spelling diverges from optic's) — a wrong/loose entity match stamps onto the wrong player. Prefer exact normalized equality; drop on ambiguity. Guard #4 (clob cross-check) still applies.
- **THREE_WAY**: `"Will <Team> win…?"` must resolve <Team> to exactly one of {home, away}; if it matches neither (or both, via loose containment) → drop. The draw form must name both teams and match the fixture pair.
- **Spread**: the favorite/underdog sign convention must match optic's (`line = odd.points`, positive = underdog). Polymarket "Spread: <Team> (-2.5)" — the named team carries the stated (usually negative) line; the opposite outcome's line is negated. Bind each label→team, each team→its signed line; drop if the two lines aren't equal-and-opposite.
- **1H vs full-game**: period totals ("1st Half O/U", "1st N Innings") must map to the FIRST_HALF_*/period type, never the full-game type — a period total stamped onto the full-game optic row is a wrong-market mismap (the same class as the Wave-2 prefix-descriptor finding). Recognizers must be anchored.

## Phasing (execution order — one SDD wave each, all on `feat/polymarket-optic-matcher`)

- **Phase 3 — matcher-core generalization + MLB full taxonomy.** Refactor to `(Scope,Shape)` dispatch + `market_rules`; add MLB prop MarketTypes; wire MLB `market_rules` (player props HR/K/Hits/Bases, run_line spread, team_total, 1st-inning total). Biggest single volume (props ~745). MLB behavior for existing ml/total stays byte-identical.
- **Phase 4 — soccer (mls/liga_mx/ucl).** 3 new modules + KALSHI-optional; rules for game_total, asian-handicap spread, 3-way ML (win/draw decomposition), BTTS, team_total, 1H totals, total_corners, anytime-scorer.
- **Phase 5 — WNBA.** New module; ml/total/spread only.
- **Phase 6 — UFC/MMA.** New Sport + League + MMA MarketTypes + module; ml/total_rounds/go_the_distance/method_of_victory/round_betting.

Each phase: SDD (implementer → task review → fixes), whole-branch flip-safety review at phase end, full `tests/mappers/` green with no regression. Consumer side (mmpolymarketrfq `common/mapping_loader.py` union-read) already reads whatever `market_mapping` contains — no consumer change needed per phase; the pre-live SA-grant + side-correctness audit gate still governs turning `USE_MARKET_MAPPING` on in the pod.

## Testing strategy

- Per market form: a `parse_question`/`build_rows` unit test with a real bridge question string + real outcome labels, asserting `(market_type, entity, line, side)` per outcome and drop-on-ambiguity.
- Per league: an end-to-end integration test (parse → `_match_poly_fixture` → `build_rows` → `attach_polymarket_row`) asserting the correct optic row is stamped with the correct clob, AND that a wrong-entity/wrong-side variant is dropped (proves flip-safety, mirrors the tennis/mlb integration tests).
- Golden-row regression: existing MLB ml/total + tennis ml outputs unchanged.

## Non-goals

WNBA player props (optic doesn't price); tennis set/game totals (optic ships tennis moneyline only); soccer correct-score / any-other-score / halftime-lead / to-score-first / 2H-winner; MLB "tied after N innings"; any esports / low-tier-soccer league optic doesn't price; the pod SA read-grant + live-enable (separate ops gate).
