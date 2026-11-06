# Market Mapper — Requirements

## Update 2026-02-23

I spoke to Nick:

- Keep validating against the Optic data
- Can use whatever langauge I like (will be Kotlin)
- INPUT: Raw exchange API response in JSON
- OUTPUT: Our own JSON shapes
- Priorities are 1. NBA, 2. College basketball, 3. Soccer
- Need to be carfully on start time — easy for NBA but, for example, 
  some start times account for singing the national anthem(!), while others don't
- Focus on the project, do not get pulled too early into the team / Bern whirlwind!

## Motivation

We are building a market-making platform that offers bets to consumers
across multiple prediction-market exchanges. To price and hedge these
bets we must continuously identify **which markets on different
exchanges represent the same real-world outcome** — a process we call
**market mapping**.

### The problem

Prediction-market exchanges let users bet on real-world events, but
each exchange structures and names its markets independently:

- **Different hierarchies.** Kalshi publishes flat, self-contained
  binary contracts (e.g. `KXNBA-26-WAS` — "Will Washington win the
  2026 NBA Finals?"). ProphetX nests selections inside markets inside
  events (event → market type → selection/line).

- **Different naming.** One exchange may list "LeBron James," another
  just "Lebron." Team names, abbreviations, and spellings vary.

- **Different terminology.** The same bet structure can be labelled
  YES/NO, HOME/AWAY, OVER/UNDER, HOME_SPREAD/AWAY_SPREAD, or
  Back/Lay depending on the exchange and market type.

- **Different market granularity.** A single Kalshi contract may
  correspond to one selection within a ProphetX market that itself
  contains multiple alternate lines.

Without a reliable mapping between these representations, we cannot
determine that a 52-cent YES on Kalshi and a +120 on ProphetX are
opposite sides of the same outcome — and therefore cannot identify
arbitrage or set our own prices.

### Why we need our own mapping

Today we receive pricing data from Optic Odds. As a side-effect,
Optic's `source_ids` field provides an implicit market map: each odds
entry cross-references the corresponding ProphetX `event_id` /
`selection_id` and Kalshi `market_id`. This is useful but insufficient
for two reasons:

1. **Coverage gaps.** Optic only sends data for markets that already
   have prices. As a market maker we want to offer bets in markets
   *before* pricing activity begins — precisely the markets for which
   Optic provides no mapping.

2. **Independence.** Relying on a third party for a core input to our
   pricing pipeline is a strategic risk. We need to produce and own
   the mapping ourselves.

We do not know what method Optic uses to produce its market map —
presumably some combination of code, AI, and human curation. Regardless,
their existing mapping is a valuable verification signal: we can use it
to validate our own mapper's output where the two overlap.

### Approach: a canonical market list

Rather than mapping Exchange A directly to Exchange B (which scales
poorly as we add exchanges), we maintain our own **canonical market
list** — a normalised registry of real-world outcomes that we own and
control.

The workflow:

1. **Ingest** market data from each exchange (Kalshi, ProphetX, and
   soon Pred) on a regular cadence (hourly batch).
2. **Seed / update** canonical entries from exchange data, enriched
   where possible with third-party reference data (e.g. NBA rosters,
   schedules) to normalise participant names and event metadata.
3. **Match** each exchange-specific market to its canonical entry
   using fuzzy matching, producing a confidence score.
4. **Review** — matches above a confidence threshold are accepted
   automatically; those below are flagged for human review. Confirmed
   matches are canonical until the underlying market structure (not
   prices) changes.

Because naming is inconsistent and market structures diverge, matching
is inherently fuzzy. We expect to combine deterministic rules, our own
heuristic mapper, and AI-assisted matching, using a consensus model to
arbitrate disagreements and flag uncertain cases for human review.

If AI is used in the matching process, it is essential that it maintains
a **persistent knowledge base** of mapping decisions and their
rationale — not just the outcomes but the basis for each decision. For
example, once the system determines that "LeBron" on one exchange refers
to "LeBron James" on another, that resolution must be recorded and
reused automatically, not re-derived from scratch on every run.

### Scope

- **Exchanges:** Kalshi, ProphetX, Pred (TBD — launching in ~2 weeks,
  data format unknown).
- **Market types:** Sports markets only (NBA initially).
- **Output:** A durable market map that associates each exchange's
  market/selection identifiers with a canonical market ID.
- **Non-goal:** Trade execution. This system produces the map;
  downstream systems consume it to identify arbitrage and place
  orders.

### Timeline pressure

We are **required** to market-make on the Pred exchange at launch
(~2 weeks). If the automated mapper is not ready by then, we will
perform the mapping manually. This is the hard deadline that shapes
our prioritisation: a correct-but-incomplete automated mapper
supplemented by manual review is preferable to a comprehensive system
delivered late.
