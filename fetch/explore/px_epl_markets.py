"""Explore PX EPL market names and types.

Usage:
    python -m fetch.explore.px_epl_markets
"""

from fetch.px import (
    GET_MARKETS_PATH,
    fetch_events,
    load_credentials,
    login,
    px_get,
)

EPL_TOURNAMENT_ID = 17


def _sel_strike(sel: dict):
    """Handicap/threshold from CFTC or legacy selection keys."""
    return sel["strike"] if "strike" in sel else sel.get("line")


def main():
    access_key, secret_key = load_credentials()
    token = login(access_key, secret_key)

    events = fetch_events(EPL_TOURNAMENT_ID, token)
    print(f"{len(events)} events")

    # Show first event's raw markets for the 3 types we care about
    ev = events[0]
    eid = ev["event_id"]
    comps = ev.get("competitors", [])
    names = " vs ".join(c["name"] for c in comps)
    print(f"\n=== Event {eid}: {names} ===")

    result = px_get(GET_MARKETS_PATH, {"event_id": str(eid)}, token)
    for m in result["data"]["markets"]:
        name = m["name"]
        if name in ("Moneyline (2 Way)", "Spread (Regular Time)",
                     "Total Goals (Regular Time)"):
            print(f"\n--- {name} (type={m['type']}) ---")
            # Show selections or market_strikes / market_lines
            if m.get("selections"):
                for s in m["selections"]:
                    print(f"  sel: outcome_id={s[0]['outcome_id']}  "
                          f"display_name={s[0]['display_name']!r}  "
                          f"line={_sel_strike(s[0])}")
            rows = m.get("market_strikes") or m.get("market_lines") or []
            for ml in rows:
                ml_line = ml["strike"] if "strike" in ml else ml.get("line")
                print(f"  market_line: line={ml_line}")
                for s in ml["selections"]:
                    print(f"    sel: outcome_id={s[0]['outcome_id']}  "
                          f"display_name={s[0]['display_name']!r}  "
                          f"line={_sel_strike(s[0])}")


if __name__ == "__main__":
    main()
