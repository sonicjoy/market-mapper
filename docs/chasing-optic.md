# Chasing Optic

When a mapping run reports fixtures missing from Optic — and we've
confirmed they're genuinely absent from the schedule source rather than
a problem on our side — we need to chase Optic to get them added.

## How to tell it's an Optic problem

The mapping run prints lines like:

    kalshi: KXNBAGAME-26MAR15UTASAC: no Optic fixture for 2026-03-15 UTA@SAC — skipping
      Both teams are known canonicals — game likely missing from schedule source.

The second line is a good indicator but not definitive.  Before
chasing Optic, investigate by checking the raw Optic fetch fixture
data to confirm the game is genuinely missing from their feed.

## Method

1. **Slack first.** Post in the OpticOdds shared channel. Keep it
   short: state the sport/league, what's missing, and include the
   query params you're using.  Slack is faster and usually enough.

2. **Gmail to get real attention.** Email `clients@opticodds.com`.
   Optic's devs are in different time zones, so email is the way to
   make sure someone actually sees it.  Include the full connection
   query params and the specific fixtures or leagues affected.  CC
   the team.

In both cases Optic will usually ask for sportsbooks and query params,
so include them up front to save a round trip.  You can also link to
the Optic dashboard to show that coverage exists there but isn't
coming through the feed:

    https://app.opticodds.com/screen/tab/-1?sport=basketball&league=ncaab&market=point_spread&date=2026-03-14_%2B11%3A00

## Examples

### Slack: missing soccer league prices

    Andrey Sapozhenko  [4:05 AM]
    Hi, we are not getting any prices for soccer league
    france_-_ligue_1, could you please check?

    Leo Barker  [4:25 AM]
    Hi Andrey, for what bookmakers?

    Andrey Sapozhenko  [4:29 AM]
    {
      'exclude_fees': 'true',
      'league': [
        'france_-_ligue_1'
      ],
      'market': [
        'moneyline',
        'total_goals',
        'both_teams_to_score',
        'asian_handicap'
      ],
      'sportsbook': [
        'bc_game',
        'coral',
        'sbobet',
        'bodog',
        '4cx',
        'novig',
        'sx_bet',
        'william_hill',
        'dafabet',
        'pinnacle',
        'sky_bet',
        'draftkings',
        'fanduel',
        'hard_rock',
        'prophet_x',
        '888sport',
        'ladbrookes',
        'bwin',
        'unibet',
        'robinhood',
        'betano',
        'kalshi',
        'polymarket'
      ]
    }

    Alex Gerson  [4:31 AM]
    Hi Andrey, I just ran the moneyline market for DraftKings using
    this url and was able to receive results:
    https://api.opticodds.com/api/v3/fixtures/odds?sportsbook=DraftKings&fixture_id=20260313A6A8308B&market=Moneyline

    [4:33 AM]
    I am also seeing results here on the screen:
    [screenshot of https://app.opticodds.com dashboard showing live coverage]

    Andrey Sapozhenko  [4:45 AM]
    Thanks. Do you know if soccer prices for france_-_ligue_1 is
    coming on sse connection as well?

    Alex Gerson  [5:08 AM]
    yes, they are!

    Andrey Sapozhenko  [5:50 AM]
    Thanks, we also recive them now

### Gmail: missing league in SSE feed

    Subject: Re: France - Ligue 1 missing from odds feed

    Dominic Calleja:
    Hi we've received no Ligue 1 prices for several days through the
    sse feed

    Roger at OpticOdds <clients@opticodds.com>:
    Hey,

    Please specify what sportsbooks you are requesting? We have full
    support for that league, so we need a bit more information to be
    able to assist.

    [screenshot of Optic dashboard showing the league is covered]

    Dominic Calleja:
    {"sportsbook" : [ "bc_game", "coral", "sbobet", "bodog", "4cx",
            "novig", "sx_bet", "william_hill", "dafabet", "pinnacle",
            "sky_bet", "draftkings", "fanduel", "hard_rock",
            "prophet_x", "888sport", "ladbrookes", "bwin", "unibet",
            "robinhood", "betano", "kalshi", "polymarket"],
        "sport": "soccer",
        "leagues": [ "france_-_ligue_1"],
        "markets": [ "moneyline", "total_goals",
            "both_teams_to_score", "asian_handicap"],
        "exclude_fees": "true"}

    https://api.opticodds.com/api/v3/soccer

    Dominic Calleja (follow-up):
    Getting nothing through the feed. I can see prices in the dash.
    Also missing WTA tennis, getting atp.

    Here are the connection query params

      {
        "sport": "soccer",
        "leagues": [ "france_-_ligue_1"],
        "markets": [ "moneyline", "total_goals",
            "both_teams_to_score", "asian_handicap"]
      },
      {
        "sport": "tennis",
        "leagues": [ "atp", "wta"],
        "markets": [ "moneyline"]
      },

    Roger at OpticOdds:
    What specific sportsbooks are you making requests for?

    Can you provide the full url you are connecting to with all query
    parameters.
