## 3 March 2026

Nick:

We should also start using grouping_key for market mapping (@Greg Tod) and mapping individual prices too. Not a top priority because the only markets that need it right now are H2H player props.
(See grouping_key in NHL Optic where market_id is player_assists_h2h_moneyline.)


Optic generally use "name" for a human-readable summary of their structured data (so we ignore it) but now I've found exceptions (only in UFC so far).
We should check our mapping logic again.

E.g. "name" has info that the structured data doesn't:
```json
{
"id": "39179-15316-2026-02:method_of_victory:draw",
"market": "Method of Victory",
"name": "Draw",
"selection": "",
"normalized_selection": "",
"market_id": "method_of_victory",
"selection_line": null,
"player_id": null,
"team_id": null,
"grouping_key": "default",
"points": null,
"source_ids": {}
}, {
"id": "39179-15316-2026-02:round_betting:juliana_miller_1st_round",
"market": "Round Betting",
"name": "Juliana Miller :: 1st Round",
"selection": "",
"normalized_selection": "",
"market_id": "round_betting",
"selection_line": null,
"player_id": null,
"team_id": "CA5EDA2F5A52B7A8",
"grouping_key": "default",
"points": null,
"source_ids": {}
}
```

E.g. "name" is just human-readable summary:
```json
{
"id": "39179-15316-2026-02:team_to_win_by_knockout_submission_dq:carli_judice_no",
"market": "Team To Win By Knockout/Submission/DQ",
"name": "Carli Judice No",
"selection": "Carli Judice",
"normalized_selection": "carli_judice",
"market_id": "team_to_win_by_knockout_submission_dq",
"selection_line": "no",
"player_id": null,
"team_id": "822929320694",
"grouping_key": "carli_judice",
"points": null,
"source_ids": {}
}, {
"id": "39179-15316-2026-02:total_rounds:over_0_5",
"market": "Total Rounds",
"name": "Over 0.5",
"selection": "",
"normalized_selection": "",
"market_id": "total_rounds",
"selection_line": "over",
"player_id": null,
"team_id": null,
"grouping_key": "default:0.5",
"points": 0.5,
"source_ids": {}
}
```

Dom:

@Victor Popa @Greg Tod only deploying terraform from gitlab cicd pls
[9:27 PM]the pipeline will run the plan automatically when you submit the MR
you can review it, then merge
after you merge it will run the plan again (final check if you want)
then you need to actively click execute to run the apply step

## 28 February 2026

I've had another go at explaining! There are 2 relevant questions for each possible market. I've focussed on Kalshi for clarity but the same applies to Prophet X and any other exchange we want to market make.

Does Kalshi have this market?

KALSHI_PRICED_MARKET: Yes and it is priced, i.e. someone is making this market.
KALSHI_UNPRICED_MARKET: Yes but it isn't priced, i.e. no-one is making this market.
KALSHI_NO_MARKET: No.

2. Does Optic have SPORTSBOOK prices for this market?

OPTIC_SB_PRICED_MARKET: Yes.
OPTIC_SB_UNPRICED_MARKET: No.

There are 6 possible situations:

KALSHI_PRICED_MARKET & OPTIC_SB_PRICED_MARKET: We can easily make this Kalshi market (and someone already is). The market is in both kalshi_markets.json and optic_fixture_odds.json. Optic gives us sportsbook prices and "source_ids" that map Optic ids to Kalshi ids.
KALSHI_UNPRICED_MARKET & OPTIC_SB_PRICED_MARKET: We WANT to make this Kalshi market (and no-one already is) BUT WE CAN'T without your help! The market is in both kalshi_markets.json and optic_fixture_odds.json. Optic gives us sportsbook prices. BUT Optic DOESN'T give us "source_ids" that map Optic ids to Kalshi ids--this is what we need from you!
KALSHI_NO_MARKET & OPTIC_SB_PRICED_MARKET: There is no Kalshi market for us to make. There are sportsbook prices in optic_fixture_odds.json (but no Kalshi "source_ids" because there is no Kalshi market). Most of the markets in optic_fixture_odds.json will be like this; you should ignore these.
KALSHI_PRICED_MARKET & OPTIC_SB_UNPRICED_MARKET: This is unusual! Someone is making this Kalshi market but it would never be us. The market is in both kalshi_markets.json and optic_fixture_odds.json. But Optic has only Kalshi prices, no sportsbook prices. Ignore this if it ever happens.
KALSHI_UNPRICED_MARKET & OPTIC_SB_UNPRICED_MARKET: This is not interesting. Kalshi has a silly market (e.g. "Which team is NBA champion in 2036?") that no-one is interested in. We're not interested either. The market is in kalshi_markets.json but not in optic_fixture_odds.json.
KALSHI_NO_MARKET & OPTIC_SB_UNPRICED_MARKET: There is nothing here!

## 19 February 2026

I changed my mind! The data is jsonl instead of csv. I've scripted it to remove prices and verbose useless data. I can make you more whenever you want!
This first batch is only NBA. The team names will be consistent/easy but there are lots of "prop" markets.

Prophet X (exchange)
https://www.prophetx.co/?currency=cash
https://partner-docs.prophetx.co/swagger/mm/index.html
Graph (most similar to Betfair): sport / tournament / sport event / market [/ market line] / selection
```
outcome_id enum:

YES = 1
NO = 2

HOME = 4
AWAY = 5

OVER = 12
UNDER = 13

HOME_SPREAD = 1714
AWAY_SPREAD = 1715
```
Kalshi (exchange)
https://kalshi.com/
https://docs.kalshi.com/api-reference
Their graph seems very flat; basically only markets. There are event objects but they have almost no data.

Optic Odds (price source and our current market mapper)
https://developer.opticodds.com/reference/getting-started
The mappings that we are currently using are in "source_ids":
Kalshi: market_ticker and side (yes/no).
Prophet X: line_id (which should be called "side id"; it's globally unique; we don't need event_id).

We definitely have priorities!

NFL (finished now)
NBA
college basketball (I'll send you some)
soccer (we started getting this from optic this week)
MLB (when the season starts)
MMA (which WSD has good prices for)


I'll collect more events today and this weekend and send them to you!

I've grabbed all the Kalshi series for our main sports. Each one is almost just a ticker and a brief title but there are some urls and links to pdfs that might add more info (I haven't looked).
Prophet X has very little sport today. (They are more limited than Kalshi.) Saturday will be much better so I'll grab lots for you then and Sunday.

## Notes on risk and bet times

24 Feb 2026

Tonight's game start times:

00:00: 1x NBA + 3x NCAAB (should settle between 02:00 and 02:30)
00:30: 4x NCAAB
01:00: 1x NBA + 1x NCAAB
02:00: 1x NCAAB
02:30: 1x NBA


Event risk controls:

Want less risk on small games (NCAAB) than big games (NBA).
TODO:
Config "max risk per market" should depend on tournament.
Config "max risk per event" also needed (and also depends on tournament).

Time risk controls:

Matched time: Want balance available up until start of each game; not all matched hours beforehand.
Settled time: Want balance recycled each day; not all committed to parlays that settle when the last game finishes.
Suggested approach is a balance schedule entered manually each day:
Maximum flexibility: Can be as broad (windows) or as detailed as BM desires.
Linear interpolation of current time interval, e.g. if we are 3/4 through an interval that starts with balance 100% available and ends with balance 0% available then we require at least 25% available at this time.



Examples of balance minimum-availability schedule:

Broad example:

Mon 18:00: 100% (Betting starts)
Tue 02:00: 0% (First window ends)
Tue 02:15: 20% (At least 20% available (recycled) 15 minutes before last game for SGPs)
Tue 02:30: 0% (Last NBA starts)
Tue 05:00: 100% (Reject all parlays that would settle later than this, e.g. championship.)


Detailed example:

Mon 18:00: 100% (Betting starts)
Tue 00:00: 60% (1x NBA and 3x NCAAB start)
Tue 00:30: 40% (4x NCAAB start)
Tue 01:00: 5% (1x NBA and 1x NCAAB start)
Tue 02:00: 0% (1x NCAAB starts)
Tue 02:15: 20% (1x NBA and 3x NCAAB settle)
Tue 02:30: 0% (1x NBA starts)
Tue 05:00: 100%


This suggested approach is a bit awkward and requires a person to consider:

Start times of events
Settlement times of events
Start-betting times of events
But those all seem necessary (unless I'm overthinking this).