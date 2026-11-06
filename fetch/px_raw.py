"""Dump raw PX API response for a single event's markets."""

import json
import sys

from fetch.px import GET_MARKETS_PATH, load_credentials, login, px_get

event_id = int(sys.argv[1])

access_key, secret_key = load_credentials()
token = login(access_key, secret_key)

result = px_get(GET_MARKETS_PATH, {"event_id": str(event_id)}, token)
print(json.dumps(result, indent=2))
