import json
from asyncio import CancelledError, run

from MMutils.handlers.async_secrets import get_secrets_manager

from MMProphetx.clients.prophet_x_http_client import (
    ProphetXAuth, ProphetXHTTPClient)

PROJECT_ID = "rs-marketmaking"
ENCODING = "utf8"


async def main():
    secrets_manager = get_secrets_manager(PROJECT_ID)
    access_key = await secrets_manager.get_secret("prophet_x_access_key_2")
    secret_key = await secrets_manager.get_secret("prophet_x_secret_key_2")

    auth = ProphetXAuth(access_key, secret_key, latency=10)

    px_client = ProphetXHTTPClient(auth, logging_environment="local")

    await px_client.start()

    try:
        # tournaments = await px_client.get_tournaments()
        # print(tournaments)
        # return

        tids = [
            # 31,  # NFL

            # 132,  # NBA
            648,  # College basketball

            # 234,  # NHL

            # 8,  # La Liga
            # 17,  # Premier League
            # 23,  # Serie A
            # 34,  # Ligue 1
            # 35,  # Bundesliga
            # 242,  # MLS

            # 1500000003,  # UFC
        ]

        events = [
            ev
            for tid in tids
            for ev in await px_client.get_sport_events(
                tournament_id=tid, max_tries=3)
        ]

        with open(
                "/dump/main/wsd/mm/data/greg/prophetx_events.jsonl", "w",
                encoding=ENCODING) as file:
            for ev in events:
                print(json.dumps(ev), file=file)

        with open(
                "/dump/main/wsd/mm/data/greg/prophetx_markets.jsonl", "w",
                encoding=ENCODING) as file:
            for ev in events:
                for m in await px_client.get_markets(ev["event_id"], max_tries=3):
                    for ml in m.get("market_lines", [m]):
                        sides = [
                            side_price_levels[0]
                            for side_price_levels in ml["selections"]
                        ]
                        for s in sides:
                            del s["display_odds"]
                            del s["odds"]
                            del s["stake"]
                            del s["value"]
                            del s["updated_at"]

                        ml["selections"] = sides

                    print(json.dumps(m), file=file)
    finally:
        try:
            await px_client.stop()
        except CancelledError:
            pass

run(main())
