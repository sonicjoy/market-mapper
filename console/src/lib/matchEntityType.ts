/** Match-side entity type (home/away). Tennis stays team; player is props. */

const FIGHTER = /ufc|boxing|mma/i;

export function matchEntityType(league: string, sport = ""): "team" | "fighter" {
  const n = `${league} ${sport}`;
  return FIGHTER.test(n) ? "fighter" : "team";
}

export function resolveEntityType(
  explicit: string | undefined,
  league: string,
  sport = "",
  fromMeta = "",
): "team" | "fighter" {
  const raw =
    (explicit ?? "").trim() || fromMeta.trim() || matchEntityType(league, sport);
  return raw === "fighter" ? "fighter" : "team";
}
