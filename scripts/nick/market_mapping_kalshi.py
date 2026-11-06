import json
from asyncio import CancelledError, run
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from MMutils.handlers.async_secrets import get_secrets_manager

from MMkalshi.clients.kalshi_http_client import KalshiHTTPClient
from MMkalshi.general.helpers import Environment

PROJECT_ID = "rs-marketmaking"
ENCODING = "utf8"


async def main():
    # Get secrets asynchronously
    secrets_manager = get_secrets_manager(PROJECT_ID)
    key_id = await secrets_manager.get_secret("wsd_1_kalshi_api_key")
    key_content = await secrets_manager.get_secret("wsd_1_kalshi_private_key")
    private_key = serialization.load_pem_private_key(
        key_content.encode("utf-8"), password=None)

    client = KalshiHTTPClient(
        key_id=key_id,
        private_key=private_key,
        environment=Environment.PROD,
        logging_environment="local",
        proxy=None)

    TAG = (  # Tags for the Sports category:
        # "Soccer",
        # "Basketball",
        # "Baseball",
        # "Football",
        # "Hockey",
        # "MMA",
        # "Cricket",
    )

    COMPETITIONS = [  # I can't work out how to use these.
        # Basketball:
        # "Pro Basketball (M)",
        # "College Basketball (M)",

        # Baseball:
        # "Pro Baseball",
        # "College Baseball",

        # Soccer:
        # "Bundesliga",
        # "Champions League",
        # "EPL",
        # "La Liga",
        # "Ligue 1",
        # "MLS",
        # "Serie A",
    ]

    SERIES_LIST = [
        # NBA:
        # "KXNBA",  # NBA Championship
        # "KXNBA1HSPREAD",  # Pro Basketball 1st Half Spread
        # "KXNBA1HTOTAL",  # NBA 1st Half Total Points
        # "KXNBA1HWINNER",  # Pro Baskeball 1st Half Winner
        # "KXNBA1QSPREAD",  # Pro Basketball 1st Quarter Spread
        # "KXNBA1QTOTAL",  # NBA 1st Quarter Total
        # "KXNBA1QWINNER",  # NBA 1st Quarter Winner
        # "KXNBA2D",  # Pro Basketball Double Double
        # "KXNBA2HSPREAD",  # Pro Basketball 2nd Half Spread
        # "KXNBA2HTOTAL",  # NBA 2nd Half Total Points
        # "KXNBA2HWINNER",  # Pro Basketball 2nd Half Winner
        # "KXNBA2QSPREAD",  # Pro Basketball 2nd Quarter Spread
        # "KXNBA2QTOTAL",  # NBA 1st Quarter Total
        # "KXNBA2QWINNER",  # NBA 2nd Quarter Winner
        # "KXNBA3D",  # Pro Basketball Triple Double
        # "KXNBA3PT",  # Pro Basketball Player Threes
        # "KXNBA3PTCONTEST",  # NBA 3-Point Contest Winner
        # "KXNBA3QSPREAD",  # Pro Basketball 3rd Quarter Spread
        # "KXNBA3QTOTAL",  # NBA 3rd Quarter Total
        # "KXNBA3QWINNER",  # NBA 3rd Quarter Winner
        # "KXNBA4QSPREAD",  # Pro Basketball 4th Quarter Spread
        # "KXNBA4QTOTAL",  # NBA 4th Quarter Total
        # "KXNBA4QWINNER",  # NBA 4th Quarter Winner
        # "KXNBAALLSTAR",  # NBA All-Star game
        # "KXNBAALLSTARGAME",  # NBA All-Star Game Winner
        # "KXNBAALLSTARMVP",  # NBA All-Star Game MVP
        # "KXNBAALLSTARS",  # Pro Basketball All Stars
        # "KXNBAAST",  # Pro Basketball Player Assists
        # "KXNBAATLANTIC",  # NBA Atlantic Division Winner
        # "KXNBABLK",  # Pro Basketball Player Blocks
        # "KXNBACELEBRITY3PT",  # NBA Celebrity 3PT Contest
        # "KXNBACELEBRITYGAME",  # Pro Basketball All-Star Celebrity Game
        # "KXNBACENTRAL",  # NBA Central Division Winner
        # "KXNBACLUTCH",  # Pro Basketball Clutch Player of the Year
        # "KXNBACOY",  # Pro Basketball Coach of the Year
        # "KXNBACUP",  # Pro Basketball Cup Champion
        # "KXNBACUPMVP",  # Pro Basketball Cup Tournament MVP
        # "KXNBADPOY",  # Pro Basketball Defensive Player of the Year
        # "KXNBADRAFT1",  # NBA Draft First Pick
        # "KXNBADRAFT10",  # NBA Draft Tenth Pick
        # "KXNBADRAFT2",  # NBA Draft Second Pick
        # "KXNBADRAFT3",  # NBA Draft Third Pick
        # "KXNBADRAFT4",  # NBA Draft Fourth Pick
        # "KXNBADRAFT5",  # NBA Draft Fifth Pick
        # "KXNBADRAFT6",  # NBA Draft Sixth Pick
        # "KXNBADRAFT7",  # NBA Draft Seventh Pick
        # "KXNBADRAFT8",  # NBA Draft Eighth Pick
        # "KXNBADRAFT9",  # NBA Draft Ninth Pick
        # "KXNBADRAFTCAT",  # Pro Basketball Draft Category
        # "KXNBADRAFTCOMP",  # Pro Basketball Draft Comparison
        # "KXNBADRAFTCONF",  # Pro Basketball Players Drafted by Conference
        # "KXNBADRAFTINT",  # Pro Basketball International Players Drafted
        # "KXNBADRAFTPICK",  # Pro Basketball Draft Pick
        # "KXNBADRAFTTOP",  # Pro Basketball Top Draft
        # "KXNBADRAFTTOP10",  # NBA Draft Top 10 Pick
        # "KXNBADRAFTTOP15",  # NBA Draft Top 15 Pick
        # "KXNBADRAFTTOP20",  # NBA Draft Top 20 Pick
        # "KXNBADRAFTTOP25",  # NBA Draft Top 25 Pick
        # "KXNBADRAFTTOP30",  # NBA Draft Top 30 Pick
        # "KXNBADRAFTTOP5",  # NBA Draft Top 5 Pick
        # "KXNBAEAST",  # NBA Eastern Conference Championship
        # "KXNBAEAST1SEED",  # NBA Eastern Conference 1 Seed
        # "KXNBAEFINMVP",  # Pro Basketball Eastern Conference Finals MVP
        # "KXNBAFINALSEXACT",  # Pro Basketball Championship Series Score
        # "KXNBAFINALSMVP",  # Finals MVP
        # "KXNBAFINALSVIEWER",  # NBA finals viewership
        # "KXNBAFINALSVIEWERGAME7",  # NBA finals viewership
        # "KXNBAFINMVP",  # Pro Basketball Finals MVP
        # "KXNBAGAME",  # Professional Basketball Game
        # "KXNBALASVEGAS",  # Las Vegas NBA team
        # "KXNBALOTTERYODDS",  # NBA Lottery Winner Odds
        # "KXNBAMIMP",  # Pro Basketball Most Improved Player
        # "KXNBAMVP",  # Pro Basketball MVP
        # "KXNBANORTHWEST",  # NBA Northwest Division Winner
        # "KXNBAPA",  # Pro Basketball Points + Assists
        # "KXNBAPACIFIC",  # NBA Pacific Division Winner
        # "KXNBAPLAYIN",  # Which Team Will Make the Play-In Tournament
        # "KXNBAPLAYOFF",  # Pro Basketball Playoff Qualifier
        # "KXNBAPR",  # Pro Basketball Points + Rebounds
        # "KXNBAPRA",  # Pro Basketball Points + Rebounds + Assists
        # "KXNBAPTS",  # Pro Basketball Player Points
        # "KXNBARA",  # Pro Basketball Rebounds + Assists
        # "KXNBAREB",  # Pro Basketball Player Rebounds
        # "KXNBARISINGSTARS",  # Pro Basketball Rising Stars Tournament
        # "KXNBAROY",  # Pro Basketball Rookie of the Year
        # "KXNBASEATTLE",  # Seattle NBA team
        # "KXNBASERIES",  # Professional Basketball Series
        # "KXNBASHOOTINGSTARS",  # Pro Basketball Shooting Stars Contest
        # "KXNBASIXTH",  # Pro Basketball Sixth Man of the Year
        # "KXNBASLAMDUNK",  # NBA Slam Dunk Contest Winner
        # "KXNBASOUTHEAST",  # NBA Southeast Division Winner
        # "KXNBASOUTHWEST",  # NBA Southwest Division Winner
        # "KXNBASPREAD",  # Pro Basketball Spread
        # "KXNBASTL",  # Pro Basketball Player Steals
        # "KXNBATEAM",  # NBA team
        # "KXNBATEAMTOTAL",  # NBA Team Total
        # "KXNBATOP3",  # Pro Basketball Draft Lottery Top 3
        # "KXNBATOPPICK",  # Pro Basketball Draft Lottery Winner
        # "KXNBATOTAL",  # Pro Basketball Total Points
        # "KXNBATRADE",  # NBA Trade
        # "KXNBAWEST",  # NBA Western Conference Championship
        # "KXNBAWEST1SEED",  # NBA Western Conference 1 Seed
        # "KXNBAWFINMVP",  # Pro Basketball Western Conference Finals MVP
        # "KXNBAWINRECORD",  # OKC NBA Win Record
        # "KXNBAWINS",  # Pro basketball wins

        # NCAAB:
        "KXNCAABACC",  # ACC Men's Basketball Tournament
        "KXNCAABBIG10",  # Big Ten Men's Basketball Tournament
        "KXNCAABBIG12",  # Big 12 Men's Basketball Tournament
        "KXNCAABBIGEAST",  # Big East Men's Basketball Tournament
        "KXNCAABBIGTEN",  # Big Ten Men's Basketball Tournament
        "KXNCAABBSPREAD",  # College Baseball Spread
        "KXNCAABGAME",  # College Basketball Game
        "KXNCAABIVY",  # Ivy League Men's Basketball Tournament
        "KXNCAABSEC",  # SEC Men's Basketball Tournament
        "KXNCAAMACC",  # ACC MEN'S BASKETBALL TOURNAMENT
        "KXNCAAMB1HSPREAD",  # Men's College Basketball 1H Spread
        "KXNCAAMB1HTOTAL",  # College Basketball 1H Total
        "KXNCAAMB1HWINNER",  # College Basketball 1H Winner
        "KXNCAAMBGAME",  # Men's College Basketball Men's Game
        "KXNCAAMBIG12",  # Big 12 MEN'S BASKETBALL TOURNAMENT
        "KXNCAAMBIGEAST",  # Big East Men's basketball tournament
        "KXNCAAMBIGTEN",  # big ten MEN'S BASKETBALL TOURNAMENT
        "KXNCAAMBNAISMITH",  # Men's College Basketball Naismith
        "KXNCAAMBSPREAD",  # Men's College Basketball Spread
        "KXNCAAMBTOTAL",  # Men's College Basketball Total Points
        "KXNCAAMBUNDEFEATED",  # Undefeated in College Basketball Regular Season

        # NHL:
        # "KXNHL",  # Stanley Cup
        # "KXNHL4NATIONS",  # 4 nations face off
        # "KXNHLADAMS",  # NHL Jack Adams Award
        # "KXNHLANYGOAL",  # Pro Hockey Goalscorer
        # "KXNHLAST",  # Pro Hockey Assists
        # "KXNHLATLANTIC",  # NHL Atlantic Division Winner
        # "KXNHLCALDER",  # NHL Calder Memorial Trophy
        # "KXNHLCENTRAL",  # NHL Central Division Winner
        # "KXNHLEAST",  # Eastern Conference Championship
        # "KXNHLFINALSEXACT",  # NHL Championship Series Score
        # "KXNHLFIRSTGOAL",  # Pro Hockey First Goal
        # "KXNHLGAME",  # NHL Game
        # "KXNHLGOAL",  # Pro Hockey Goalscorer
        # "KXNHLHART",  # NHL Hart Memorial Trophy
        # "KXNHLMETROPOLITAN",  # NHL Metropolitan Division Winner
        # "KXNHLNORRIS",  # NHL James Norris Memorial Trophy
        # "KXNHLPACIFIC",  # NHL Pacific Division Winner
        # "KXNHLPLAYOFF",  # Playoff Qualifier
        # "KXNHLPRES",  # NHL President's Trophy Winner
        # "KXNHLPTS",  # Pro Hockey Points
        # "KXNHLRICHARD",  # NHL Maurice "Rocket" Richard Trophy
        # "KXNHLROSS",  # NHL Art Ross Trophy
        # "KXNHLSAVES",  # Pro Hockey Saves
        # "KXNHLSERIES",  # Professional Hockey Series
        # "KXNHLSPREAD",  # NHL Spread
        # "KXNHLTOTAL",  # NHL Goal Total
        # "KXNHLVEZINA",  # NHL Vezina Trophy
        # "KXNHLWEST",  # Western Conference Champion
        # "KXNHLWINS",  # NHL wins

        # Soccer:
        # "KXBUNDESLIGA",  # BUNDESLIGA
        # "KXBUNDESLIGABTTS",  # Bundesliga BTTS
        # "KXBUNDESLIGAGAME",  # Bundesliga Game
        # "KXBUNDESLIGARELEGATION",  # Bundesliga Relegation
        # "KXBUNDESLIGASPREAD",  # Bundesliga Spread
        # "KXBUNDESLIGATOP4",  # Bundesliga Top 4 Finishers
        # "KXBUNDESLIGATOTAL",  # Bundesliga Total
        # "KXEPLANYGOAL",  # EPL Anytime Goalscorer
        # "KXEPLBTTS",  # EPL Both Teams to Score
        # "KXEPLFIRSTGOAL",  # EPL 1st Goalscorer
        # "KXEPLGAME",  # English Premier League Game
        # "KXEPLGOAL",  # EPL Goalscorer
        # "KXEPLRELEGATION",  # English Premier League Relegation
        # "KXEPLSPREAD",  # English Premier League Spread
        # "KXEPLTOP2",  # Top 2 Finishers
        # "KXEPLTOP4",  # EPL top 4 teams
        # "KXEPLTOP6",  # Top 6 Finishers
        # "KXEPLTOTAL",  # English Premier League Total Goals
        # "KXLALIGA",  # LA LIGA
        # "KXLALIGA2GAME",  # LaLiga 2 Game
        # "KXLALIGABTTS",  # La Liga BTTS
        # "KXLALIGAGAME",  # La Liga Game
        # "KXLALIGARELEGATION",  # La Liga Relegation
        # "KXLALIGASPREAD",  # La Liga Spread
        # "KXLALIGATOP4",  # La Liga Top 4 Finishers
        # "KXLALIGATOTAL",  # La Liga Total
        # "KXLIGUE1",  # LIGUE 1
        # "KXLIGUE1BTTS",  # Ligue 1 BTTS
        # "KXLIGUE1GAME",  # Ligue 1 Game
        # "KXLIGUE1RELEGATION",  # Ligue 1 Relegation
        # "KXLIGUE1SPREAD",  # Ligue 1 Spread
        # "KXLIGUE1TOP4",  # Ligue 1 Top 4 Finishers
        # "KXLIGUE1TOTAL",  # Ligue 1 Total
        # "KXMLSADVANCE",  # MLS To Advance
        # "KXMLSBTTS",  # MLS BTTS
        # "KXMLSCUP",  # MLS Cup champion
        # "KXMLSEAST",  # MLS Western Conference winner?
        # "KXMLSGAME",  # Major League Soccer Game
        # "KXMLSSPREAD",  # MLS Spread
        # "KXMLSTOTAL",  # MLS Total
        # "KXMLSWEST",  # MLS Western Conference winner?
        # "KXPREMIERLEAGUE",  # PREMIER LEAGUE
        # "KXSERIEA",  # Serie A
        # "KXSERIEABTTS",  # Serie A BTTS
        # "KXSERIEAGAME",  # Serie A Game
        # "KXSERIEARELEGATION",  # Serie A Relegation
        # "KXSERIEASPREAD",  # Serie A Spread
        # "KXSERIEATOP4",  # Serie A Top 4 Finishers
        # "KXSERIEATOTAL",  # Serie A Total

        # UFC:
        # "KXUFCBANTAMWEIGHTTITLE",  # UFC Bantamweight Title
        # "KXUFCFEATHERWEIGHTTITLE",  # UFC Featherweight Title
        # "KXUFCFIGHT",  # UFC Fight
        # "KXUFCFLYWEIGHTTITLE",  # UFC Flyweight Title
        # "KXUFCHEAVYWEIGHTTITLE",  # UFC Heavyweight Title
        # "KXUFCLHEAVYWEIGHTTITLE",  # UFC Light Heavyweight Title
        # "KXUFCLIGHTWEIGHTTITLE",  # UFC Lightweight Title
        # "KXUFCMIDDLEWEIGHTTITLE",  # UFC Middleweight Title
        # "KXUFCTITLE",  # UFC Title
        # "KXUFCWELTERWEIGHTTITLE",  # UFC Welterweight Title
    ]

    try:
        # tags = await client.get_tags()
        # print(tags)

        # filters = await client.get_filters()
        # print(filters)

        # sport_series = {}
        # for sport in [
        #     "Soccer", "Basketball", "Baseball", "Football",
        #     "Hockey", "MMA", "Cricket",
        # ]:
        #     sport_series[sport] = await client.get_series_list(
        #         category="Sports", tags=sport)
        # with open(
        #         "/dump/main/wsd/mm/data/greg/kalshi_sport_series.json", "w",
        #         encoding=ENCODING) as file:
        #     json.dump(sport_series, file)

        # series = await client.get_series_list(
        #     category="Sports",
        #     tags="Hockey",
        # )
        # for s in sorted(series["series"], key=lambda s: s["ticker"]):
        #     print(f'"{s["ticker"]}",  # {s["title"]}')

        # events = await client.get_events(
        #     series_ticker="KXNBAGAME",
        #     with_nested_markets=True,
        #     status="open")
        # print(events)

        max_close_ts = int(
            (datetime.now(timezone.utc) + timedelta(days=7))
            .timestamp())
        markets_list = []
        for series in SERIES_LIST:
            markets = await client.get_markets(
                series_ticker=series,
                status="open",

                # Filters the series, not individual markets?
                # max_close_ts=max_close_ts,
            )
            markets_list += markets["markets"]

        keys = (
            "event_ticker,ticker,title,subtitle,yes_sub_title,no_sub_title,"
            "market_type,status,"
            "created_time,open_time,close_time,expected_expiration_time,"
            "rules_primary,rules_secondary"
            .split(","))

        with open(
                "/dump/main/wsd/mm/data/greg/kalshi_markets.jsonl", "w",
                encoding=ENCODING) as file:
            for m in markets_list:
                print(json.dumps({k: m[k] for k in keys}), file=file)
    finally:
        try:
            await client.close()
        except CancelledError:
            pass

run(main())
