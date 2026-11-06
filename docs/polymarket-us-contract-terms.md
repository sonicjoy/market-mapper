# Polymarket US contract terms that decide our mappings

The venue's settlement terms are in each market's `description` on the public gateway
(`GET https://gateway.polymarket.us/v1/events/{id}` → `markets[].description`). The fetch does not keep
that text (`fetch/polymarket_usa.py` `market_record`), so a term that decides a mapping is written down
here, verbatim, with the date it was read. Re-read it when the venue announces a rule change.

## Soccer (read 2026-10-21: 99 live player props, 11 events, La Liga / MLS / UCL / US Open Cup)

| Market family | Venue terms (verbatim) | Optic market it equals |
|---|---|---|
| Player props, every `soccer_player_*` (goals, first goal, goals + assists, saves …) | "Extra time is included if played. Penalty shootouts are not included if played. Own goals do not count. If the listed player does not start the match, the market will settle to the last fair market price." (identical on all 99) | Optic's `player_goals`, `player_assists`, `first_goal_scorer` … settle on 90 minutes plus stoppage. **Equal only where extra time cannot be played.** |
| Full-game team markets (winner, spread, total, team total, BTTS, exact score, first to score, corners) | "at the end of 90 minutes plus stoppage time" / "during 90 minutes plus stoppage time" / "in full time (90 minutes plus stoppage time)" | Optic's regulation markets, any stage. |
| Half markets | "during the first half of regulation"; second half adds "Extra time and penalty shootouts are not included." | Optic `1st_half_*` / `2nd_half_*`, any stage. |
| To advance (`soccer_game_to_advance`) | "determined by any official result including extra time and penalty shootouts" | Not mapped (no entry in `mappers/vocab/poly_usa_smt.py`). |

The change was announced by the venue for 2026-10-21; the first affected event was the US Open Cup tie
`astatc-usoc-clb-stl-2026-10-21` ("No Goalscorer" settles only if nobody scores through extra time; team
markets unchanged). The text is now on league games too, where it changes nothing.

### How the mapper applies it (`mappers/exchanges/polymarket_usa_extra_time.py`)

- A player prop maps only when its Optic fixture's league **and** `season_type` are listed in
  `REGULATION_ONLY_STAGES` **and** no book on the fixture quotes `to_advance`, an `*_incl_et` market or an
  `extra_time_*` market. Anything else, including a stage label nobody has listed, a fixture fetched
  without `season_type`, and every cup, is treated as "extra time possible".
- On such a fixture the prop is held (log: `player props held (extra time possible)`), and an Optic
  `Polymarket (USA)` passthrough on it is stripped with reason `extra_time`. A passthrough on a player
  row of that fixture is stripped too when its symbol is missing from our gateway snapshot (an event
  whose detail fetch failed has no props in it). Missing beats wrong.
- Optic's catalogue has `*_incl_et` twins (`player_goals_incl_et`, `first_goal_scorer_incl_et`,
  `player_goals_+_assists_incl_et` …), but no book quoted one on the eight knockout fixtures probed on
  2026-10-21 (DFB-Pokal Round 2, EFL Cup Round of 16, Copa do Brasil and Libertadores semi-finals; 183
  books, market-filtered). Until a book quotes them there is nothing to map onto, so the twins are not wired.

### Adding a stage

List a `(league, season_type)` only when no match in it can go to extra time, with the format rule in the
comment. Two-legged ties, cup rounds, playoffs and finals stay out. Check the label Optic actually uses
(`/fixtures/active?league=…` → `season_type`). The UCL league phase is `Group Stage`; its qualifying and
knockout rounds carry other labels (`Playoffs`, `Round of 16` …) and so stay unlisted.

### Open: a substitute's goals

"If the listed player does not start the match" settles at the last fair market price. Books settle a
substitute's goals normally, and no Optic market is conditional on starting. This applies to every soccer
prop we map, including the league phase. It is not handled in the mapper.

## Basketball

| Market family | Venue terms (verbatim) | Optic market it equals |
|---|---|---|
| NBA second-half team total (`basketball_team_total_points_second_half`) | "Overtime is included if played." (event 135241, read 2026-10-20) | `2nd_half_team_total_incl_ot` (MR !508) |
