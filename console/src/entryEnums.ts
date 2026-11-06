/** Closed sets for Mapper entry dropdowns (unknown prefill values still allowed). */

/** Matches mappers.shared.FIXTURE_HORIZON_HOURS (7 days). */
export const DEFAULT_FIXTURE_HORIZON_HOURS = 168;

/** One year — Editor number input cap. */
export const MAX_FIXTURE_HORIZON_HOURS = 8760;

export const ENTITY_TYPES = ["team", "player", "fighter"] as const;

export const SPORTS = [
  "soccer",
  "football",
  "basketball",
  "baseball",
  "hockey",
  "tennis",
  "mma",
  "boxing",
  "esports",
  "cricket",
] as const;

export const MARKET_ACTIONS = ["map", "ignore"] as const;

// Tip / Editor sportsbook ids — keep aligned with chat_profiles.CHAT_SPORTSBOOKS
// and mappers/control_plane/console_platforms.py (explore ids may differ, e.g. crypto).
// Kalshi is not here: it maps from Kalshi's typed fields in code, never from tip
// league pins, market rules or alias pins.
export const SPORTSBOOKS = ["crypto.com", "optic", "polymarket", "polymarket_usa", "px", "novig", "underdog", "dkex"] as const;

// Feeds that only contribute entity ids (alias pins), never league exchanges, market rules or
// Coverage columns. TxODDS is a scores feed: its TeamIds join TxODDS fixtures to Optic ones
// (tx_scores_us.txodds_optic_fixture_map); classify never reads them.
export const ALIAS_ONLY_BOOKS = ["txodds"] as const;

/** Books the structured alias form and the entities filter offer: every venue plus alias-only feeds. */
export const ALIAS_SPORTSBOOKS = [...SPORTSBOOKS, ...ALIAS_ONLY_BOOKS] as const;

/** Display labels for console sportsbook ids (matches control-plane book_label). */
export const SPORTSBOOK_LABELS: Record<string, string> = {
  kalshi: "Kalshi",
  "crypto.com": "crypto.com",
  optic: "Optic",
  polymarket: "Polymarket",
  polymarket_usa: "Polymarket US",
  px: "ProphetX",
  novig: "Novig",
  underdog: "Underdog",
  dkex: "DraftKings Exchange",
  huddle: "Huddle",
  txodds: "TxODDS",
};

export function sportsbookLabel(sportsbook: string): string {
  const book = sportsbook.trim().toLowerCase();
  return SPORTSBOOK_LABELS[book] ?? sportsbook.trim();
}

export const ALIAS_ENFORCEMENTS = ["raise", "warn"] as const;

/** Canonical market types from MarketType; keep sorted A-Z. */
/** Canonical market types from MarketType; keep sorted A-Z. */
export const CANONICAL_MARKET_TYPES = [
  "1h_btts",
  "1h_correct_score",
  "1h_double_chance",
  "1h_first_team_to_score",
  "1h_moneyline",
  "1h_point_spread",
  "1h_team_total",
  "1h_total",
  "1h_winner_3way",
  "1q_both_teams_score",
  "1q_point_spread",
  "1q_total",
  "1q_winner_3way",
  "1st_set_total_games",
  "1st_set_winner",
  "2h_btts",
  "2h_first_team_to_score",
  "2h_point_spread",
  "2h_team_total",
  "2h_team_total_incl_ot",
  "2h_total",
  "2h_winner_3way",
  "2nd_set_total_games",
  "2nd_set_winner",
  "2q_both_teams_score",
  "2q_point_spread",
  "2q_total",
  "2q_winner_3way",
  "3q_both_teams_score",
  "3q_point_spread",
  "3q_total",
  "3q_winner_3way",
  "4q_both_teams_score",
  "4q_moneyline_incl_ot",
  "4q_point_spread",
  "4q_point_spread_incl_ot",
  "4q_total",
  "4q_total_incl_ot",
  "4q_winner_3way",
  "anytime_goal_scorer",
  "both_teams_score_td",
  "btts",
  "btts_reg_time",
  "correct_score",
  "double_chance",
  "extra_innings",
  "f3_moneyline_3way",
  "f5_moneyline",
  "f5_moneyline_3way",
  "f5_point_spread",
  "f5_total",
  "f7_moneyline_3way",
  "fight_goes_distance",
  "first_10_minutes_total",
  "first_basket",
  "first_goal_scorer",
  "first_inning_total",
  "first_team_to_score",
  "first_team_touchdown",
  "first_touchdown_scorer",
  "game_total",
  "game_win_by_kotko",
  "go_the_distance",
  "halftime_fulltime",
  "highest_scoring_quarter",
  "i1_winner_3way",
  "i2_total",
  "i2_winner_3way",
  "i3_total",
  "i3_winner_3way",
  "i4_total",
  "i4_winner_3way",
  "i5_total",
  "i5_winner_3way",
  "i6_total",
  "i6_winner_3way",
  "i7_total",
  "i7_winner_3way",
  "i8_total",
  "i8_winner_3way",
  "i9_total",
  "last_touchdown_scorer",
  "map_1_first_blood",
  "map_1_kills_odd",
  "map_1_round_handicap",
  "map_1_total_rounds",
  "map_1_winner",
  "map_2_first_blood",
  "map_2_kills_odd",
  "map_2_round_handicap",
  "map_2_total_rounds",
  "map_2_winner",
  "map_3_first_blood",
  "map_3_kills_odd",
  "map_3_round_handicap",
  "map_3_total_rounds",
  "map_3_winner",
  "map_4_first_blood",
  "map_4_kills_odd",
  "map_4_winner",
  "map_5_first_blood",
  "map_5_kills_odd",
  "map_5_winner",
  "map_handicap",
  "match_total_games",
  "method_of_finish",
  "method_of_victory",
  "moneyline",
  "moneyline_3way",
  "moneyline_dnb",
  "most_passing_yards",
  "p1_point_spread",
  "p1_team_total",
  "p1_total",
  "p1_winner_3way",
  "p2_point_spread",
  "p2_team_total",
  "p2_total",
  "p2_winner_3way",
  "p3_point_spread",
  "p3_team_total",
  "p3_total",
  "p3_winner_3way",
  "pick_six",
  "player_assists",
  "player_assists_h2h_moneyline",
  "player_assists_insurance",
  "player_assists_yn",
  "player_bases",
  "player_batting_strikeouts",
  "player_batting_walks",
  "player_blocks",
  "player_blocks_yn",
  "player_cards",
  "player_double_double",
  "player_earned_runs",
  "player_field_goals_made",
  "player_fouls",
  "player_fouls_won",
  "player_games_won",
  "player_goals",
  "player_goals_or_assist",
  "player_goals_yn",
  "player_hits",
  "player_hits_allowed",
  "player_hits_runs_rbis",
  "player_home_runs",
  "player_interceptions",
  "player_interceptions_insurance",
  "player_kicking_points",
  "player_longest_passing_completion",
  "player_longest_passing_completion_insurance",
  "player_longest_reception",
  "player_longest_reception_insurance",
  "player_longest_rush",
  "player_longest_rush_insurance",
  "player_outs",
  "player_passing_+_rushing_yards",
  "player_passing_+_rushing_yards_insurance",
  "player_passing_attempts",
  "player_passing_attempts_insurance",
  "player_passing_completions",
  "player_passing_completions_insurance",
  "player_passing_touchdowns",
  "player_passing_touchdowns_insurance",
  "player_passing_yards",
  "player_passing_yards_insurance",
  "player_points",
  "player_points_insurance",
  "player_points_yn",
  "player_power_play_points",
  "player_pts_ast",
  "player_pts_ast_yn",
  "player_pts_reb",
  "player_pts_reb_ast",
  "player_pts_reb_ast_yn",
  "player_pts_reb_yn",
  "player_rbis",
  "player_reb_ast",
  "player_reb_ast_yn",
  "player_rebounds",
  "player_rebounds_insurance",
  "player_rebounds_yn",
  "player_receiving_yards",
  "player_receiving_yards_insurance",
  "player_receptions",
  "player_receptions_insurance",
  "player_red_cards",
  "player_runs",
  "player_rushing_+_receiving_yards",
  "player_rushing_+_receiving_yards_insurance",
  "player_rushing_attempts",
  "player_rushing_attempts_insurance",
  "player_rushing_yards",
  "player_rushing_yards_insurance",
  "player_sacks",
  "player_saves",
  "player_shots",
  "player_shots_on_goal",
  "player_shots_on_target",
  "player_steals",
  "player_steals_blocks",
  "player_steals_blocks_yn",
  "player_steals_yn",
  "player_stolen_bases",
  "player_strikeouts",
  "player_tackles",
  "player_tackles_+_assists",
  "player_threes",
  "player_threes_insurance",
  "player_threes_yn",
  "player_touchdowns",
  "player_touchdowns_insurance",
  "player_touchdowns_yn",
  "player_triple_double",
  "player_turnovers",
  "player_turnovers_yn",
  "player_walks_allowed",
  "point_spread",
  "point_spread_yn",
  "race_to_points",
  "round_betting",
  "set_handicap",
  "successful_2_point_conversion",
  "team_first_touchdown_scorer",
  "team_total",
  "team_total_corners",
  "team_total_field_goals",
  "team_total_first_downs",
  "team_total_passing_touchdowns",
  "team_total_passing_yards",
  "team_total_receiving_touchdowns",
  "team_total_receiving_yards",
  "team_total_receptions",
  "team_total_rushing_+_receiving_yards",
  "team_total_rushing_touchdowns",
  "team_total_rushing_yards",
  "team_total_sacks",
  "team_total_touchdowns",
  "team_total_yards",
  "to_advance",
  "to_start_round_2",
  "to_start_round_3",
  "to_start_round_4",
  "to_start_round_5",
  "total_corners",
  "total_maps",
  "total_passing_touchdowns",
  "total_passing_yards",
  "total_rounds",
  "total_rushing_touchdowns",
  "total_rushing_yards",
  "total_sets",
  "total_touchdowns",
  "will_there_be_a_safety",
  "will_there_be_overtime",
  "win_by_ko_sub_dq",
  "winning_margin",
  "winning_margin_5-way",
] as const;

/** Seeded match field per sportsbook — traders do not pick this. */
export const SOURCE_KEY_TYPE_BY_SPORTSBOOK: Record<string, string> = {
  "crypto.com": "contract_type",
  optic: "market_id",
  polymarket: "kind",
  polymarket_usa: "kind",
  px: "market_name",
  novig: "market_type",
  underdog: "product_period",
  dkex: "market_period",
};

export function sourceKeyTypeFor(sportsbook: string): string {
  return SOURCE_KEY_TYPE_BY_SPORTSBOOK[sportsbook] ?? "market_id";
}

export function sourceKeyHint(sportsbook: string): string {
  const keyType = sourceKeyTypeFor(sportsbook);
  return `Exact ${sportsbook} ${keyType} string from the feed (case-sensitive).`;
}

/** Alias kind convention per sportsbook — traders do not pick this. */
export const ALIAS_KIND_BY_SPORTSBOOK: Record<string, string> = {
  "crypto.com": "crypto_id",
  optic: "optic_id",
  polymarket: "name",
  polymarket_usa: "code",
  px: "code",
  novig: "code",
  underdog: "code",
  dkex: "code",
  txodds: "external_id",
};

export function aliasKindFor(sportsbook: string): string {
  return ALIAS_KIND_BY_SPORTSBOOK[sportsbook] ?? "code";
}

/** Default parser profiles when onboarding a league exchange pin. */
export const DEFAULT_PARSER_PROFILES: Record<string, string> = {
  optic: "optic_standard_v1",
  px: "px_generic_v1",
  "crypto.com": "crypto_generic_v1",
  polymarket: "poly_generic_v1",
  polymarket_usa: "poly_usa_generic_v1",
  novig: "novig_generic_v1",
  underdog: "underdog_generic_v1",
  dkex: "dkex_generic_v1",
  huddle: "huddle_nfl_v1",
};

export function defaultParserProfile(sportsbook: string): string {
  return DEFAULT_PARSER_PROFILES[sportsbook] ?? `${sportsbook}_generic_v1`;
}

export function sourceLeagueIdLabel(sportsbook: string): string {
  if (sportsbook === "optic") return "Optic source league id (optional)";
  if (sportsbook === "crypto.com") return "crypto.com source league id (optional)";
  if (sportsbook === "polymarket") return "Polymarket source league id (optional)";
  if (sportsbook === "polymarket_usa") return "Polymarket US league code (source_league_id)";
  if (sportsbook === "px") return "PX source league id (optional)";
  if (sportsbook === "novig") return "Novig league string (source_league_id)";
  if (sportsbook === "underdog") return "Underdog venue league (NFL, MLB, …)";
  if (sportsbook === "dkex") return "DKEX venue league (NFL, CFB, MLB, …)";
  if (sportsbook === "huddle") return "Huddle competition id (source_league_id)";
  return "Source league id (optional)";
}

/** Spinner copy while live harvest runs for one exchange toggle. */
export function harvestLoadingLabel(sportsbook: string): string {
  if (sportsbook === "polymarket_usa") return "Retrieving league code…";
  if (sportsbook === "px") return "Retrieving tournament id…";
  if (sportsbook === "novig") return "Retrieving league string…";
  if (sportsbook === "underdog") return "Retrieving venue league…";
  if (sportsbook === "dkex") return "Retrieving venue league…";
  return "Retrieving league id…";
}
