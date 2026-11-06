export type ExplorePlatform = {
  id: string;
  label: string;
  sportsbook: string;
  unmapped_inventory: boolean;
  missing_catalogue: boolean;
};

export type Meta = {
  env: string;
  operator: string;
  role: string;
  build: string;
  require_maker_checker?: boolean;
  chat_enabled?: boolean;
  catalog_enabled?: boolean;
  live_sot?: string;
  allow_activate?: boolean;
  explore_platforms?: ExplorePlatform[];
  /** Sportsbook -> why an active mapping_override there would be a no-op (Catalog refuses to publish). */
  override_unread_sportsbooks?: Record<string, string>;
  /** MAPPING_OVERRIDE_LANE: crypto.com / Polymarket (USA) overrides land in market_mapping. */
  override_lane_enabled?: boolean;
};

export type ChatReplyButton = {
  id: string;
  label: string;
  send: string;
};

export type ChatResponse = {
  reply_markdown: string;
  agent_available: boolean;
  conversation_id?: string | null;
  reply_buttons?: ChatReplyButton[];
  ui_actions?: Record<string, unknown>[];
};

export type EntryPreview = {
  summary: string;
  sportsbook_label: string;
  code: string;
  entity_name: string;
  league_label: string;
  paste: string;
  evidence?: string[];
};

export type VerifyResponse = {
  ok: boolean;
  blockers: string[];
  warnings: string[];
  preview: EntryPreview | null;
  preview_token: string | null;
  payload?: Record<string, unknown>;
  needs_name: boolean;
  needs_live_ack: boolean;
  needs_league: boolean;
  disambiguation_choices: { label: string }[];
};

export type ChangeGroup = {
  added_count: number;
  removed_count: number;
  modified_count: number;
  lines: string[];
};

export type ChangeGroups = {
  aliases: ChangeGroup;
  leagues: ChangeGroup;
  market_rules: ChangeGroup;
};

export type MappingSide = {
  platform?: string;
  name?: string;
  description?: string;
  sport?: string;
  league?: string;
  code?: string;
  id?: string;
  symbol?: string;
  slug?: string;
  alias_kind?: string;
  abbr?: string;
};

export type MappingRow = {
  kind: "alias" | "market_rule" | "league";
  key: string;
  action: "add" | "update" | "delete";
  tier: "confirmed" | "guess" | "ai";
  confidence: number | null;
  reason: string | null;
  alternatives: { name: string; code?: string }[];
  keep_default: boolean;
  league: string;
  league_label: string;
  league_is_new: boolean;
  sport: string;
  sportsbook?: string;
  rfq_demand: number | null;
  next_fixtures: ProposedFixture[];
  evidence: string[];
  source: MappingSide;
  target: MappingSide;
  proposal_ref?: string;
  clone_from?: string;
  cloned_rules?: ClonedRulePreview[];
  league_diff?: LeagueDiff;
  optic_league_id?: string;
  fixture_source?: string;
  fixture_horizon_hours?: number;
  enabled?: boolean;
  exchanges?: LeagueExchange[];
  official_description?: string | null;
  citation_url?: string | null;
  notes?: string | null;
  line_offset?: number | null;
  yes_side?: string | null;
  side_swap?: boolean | null;
  match_operator?: string | null;
  venue?: string | null;
  transform?: string | null;
  optic?: string | null;
  card_label?: string | null;
  /** Already on the tip. Shown for context; not an approvable pin. */
  read_only?: boolean;
};

export type LeagueDiff = {
  enable: string[];
  disable: string[];
  change: string[];
  already: string[];
  other: string[];
};

export type ClonedRulePreview = {
  sportsbook: string;
  sportsbook_label?: string;
  source_key: string;
  source_key_type?: string;
  action: string;
  canonical_market_type?: string;
};

export type ProposedFixture = {
  fixture_id: string;
  label: string;
  start_date?: string;
  ttko_hours?: number | null;
  rfq_demand?: number | null;
};

export type ProposedLeagueBlock = {
  league: string;
  league_label: string;
  sport: string;
  is_new: boolean;
  fixtures: ProposedFixture[];
  rows: MappingRow[];
};

export type ProposedView = {
  count: number;
  proposal_ref?: string;
  leagues: ProposedLeagueBlock[];
  rows: MappingRow[];
};

export type CoveragePlatform = {
  sportsbook: string;
  sportsbook_label: string;
  mapped_count: number;
  expected_count: number;
  markets: { canonical_market_type: string; mapped: boolean }[];
};

export type CoverageStampRow = {
  sportsbook: string;
  sportsbook_label?: string;
  market_type: string;
  market_id: string;
  entity: string;
  line: string;
  side: string;
  contract_side?: string;
  source_id: string;
  last_updated?: string | null;
};

export type CoverageFixture = {
  fixture_id: string;
  label: string;
  home?: string;
  away?: string;
  start_date?: string;
  ttko_hours?: number | null;
  optic_status?: string | null;
  league?: string;
  league_label?: string;
  sport?: string;
  status?: string;
  home_entity?: EntityRuleRow | null;
  away_entity?: EntityRuleRow | null;
  home_competitor_ids?: string[];
  away_competitor_ids?: string[];
  home_abbr?: string;
  away_abbr?: string;
  market_rules?: MarketRuleRow[];
  output_order?: string[];
  league_entity_type?: string;
  coverage?: { mapped_count: number; expected_count: number };
  league_detail?: {
    sport: string;
    optic_league_id: string;
    fixture_source: string;
    fixture_horizon_hours: number;
    enabled: boolean;
    entity_type?: string;
    alias_enforcement?: string;
    runshop_enabled?: boolean;
    exchanges: LeagueExchange[];
  };
  coverage_detail?: {
    mapped_count: number;
    expected_count: number;
    platforms: CoveragePlatform[];
    stamps?: CoverageStampRow[];
  };
};

export type MissingSymbolRow = {
  platform: string;
  symbol: string;
  symbol_base: string;
  fixture_prefix: string;
  crypto_prefix: string;
  market_group: string;
  contract_type: string;
  period_type: string;
  fixture_name: string;
  meta_league: string;
  scope: "untouched" | "extra";
  kickoff: string | null;
  ttko_hours: number | null;
  league: string;
  sport: string;
};

/** One market name (catalogue contract_type) offered by the Missing picker. */
export type MissingMarketOption = { name: string; count: number };

export type UnmappedLegRow = {
  platform: string;
  key: string;
  platform_leg_description: string;
  demand: number;
  last_seen?: string;
  league?: string | null;
  league_label?: string | null;
  sport?: string | null;
  fixture?: string | null;
  start_date?: string | null;
  ttko_hours?: number | null;
  has_fixes?: boolean;
  mappable_items?: MappableItem[];
  market_group?: string;
  contract_type?: string;
  crypto_ids?: string[];
};

export type UnmappedWhyReason = {
  code: string;
  text: string;
  actionable: boolean;
};

export type MappableItem = {
  id: string;
  kind: "league" | "alias" | "market_rule";
  label: string;
  mapped: boolean;
  fixable: boolean;
};

export type ReviewCard = {
  ref: string;
  status: string;
  summary: string;
  artifact?: string;
  sportsbook_label: string;
  code: string | null;
  entity_name: string;
  league_label: string;
  proposer: string;
  headline?: string | null;
  note?: string | null;
  evidence: string[];
  mappings?: MappingRow[];
  proposed?: ProposedView;
  changes: {
    added_count: number;
    removed_count: number;
    modified_count: number;
  } | null;
  change_groups?: ChangeGroups | null;
};

export type ReviewHistoryRow = {
  ref: string;
  at: string;
  brief: string;
  status: string;
  reviewer: string | null;
};

export type EntityAliasPin = {
  sportsbook: string;
  sportsbook_label: string;
  alias_kind: string;
  code: string;
  name?: string;
};

export type EntityRuleRow = {
  league: string;
  league_label: string;
  entity_name: string;
  entity_type: string;
  canonical_key: string;
  aliases: EntityAliasPin[];
};

export type LeagueExchange = {
  sportsbook: string;
  enabled?: boolean;
  source_league_id?: string | null;
  parser_profile?: string;
  settings?: Record<string, unknown>;
};

export type LeagueRuleRow = {
  league: string;
  league_label: string;
  sport: string;
  optic_league_id: string;
  fixture_source: string;
  fixture_horizon_hours?: number;
  enabled: boolean;
  entity_type?: string;
  exchanges: LeagueExchange[];
};

export type MarketRuleRow = {
  league: string;
  league_label: string;
  sportsbook_label: string;
  sportsbook: string;
  rule_kind: string;
  source_key_type: string;
  source_key: string;
  action: string;
  canonical_market_type: string | null;
  priority: number;
  enabled: boolean;
  match_operator?: string;
  line_offset?: number | null;
  yes_side?: string | null;
  side_swap?: boolean | null;
  official_description?: string | null;
  citation_url?: string | null;
  notes?: string | null;
  offset_text?: string | null;
  yes_side_text?: string | null;
  side_swap_text?: string | null;
  venue?: string | null;
  transform?: string | null;
  optic?: string | null;
  card_label?: string | null;
};

export type RulesResponse = {
  kind?: string;
  count: number;
  limit?: number;
  offset?: number;
  entities?: EntityRuleRow[];
  leagues?: LeagueRuleRow[];
  market_rules?: MarketRuleRow[];
};

export type EntryLocationState = {
  fromRules?: boolean;
  /** Proposed detail URL to return to after Edit (`/review/{ref}?…`). */
  returnTo?: string;
  cartItemId?: string;
  paste?: string;
  note?: string;
  tab?: "alias" | "league" | "market";
  mode?: "create" | "amend" | "remove";
  // alias structured
  league?: string;
  sportsbook?: string;
  code?: string;
  entity_name?: string;
  entity_type?: string;
  canonical_key?: string;
  alias_kind?: string;
  // league
  sport?: string;
  optic_league_id?: string;
  fixture_source?: string;
  fixture_horizon_hours?: number;
  enabled?: boolean;
  alias_enforcement?: string;
  runshop_enabled?: boolean;
  exchanges?: Record<string, unknown>[];
  /** League tab: scroll/highlight this exchange pin (from Coverage platform header). */
  focusSportsbook?: string;
  // market
  source_key?: string;
  action?: string;
  canonical_market_type?: string | null;
  source_key_type?: string;
  match_operator?: string;
  line_offset?: number | null;
  yes_side?: string | null;
  side_swap?: boolean | null;
  official_description?: string | null;
  citation_url?: string | null;
};

export type ParityMismatchRow = {
  league: string;
  sportsbook: string;
  detail: string;
};

export type ParityEvent = {
  event_id?: string;
  event_type?: string;
  occurred_at?: string;
  rule_set_id?: string | null;
  league?: string | null;
  sportsbook?: string | null;
  reason_code?: string | null;
  mismatch_count?: number;
  payload?: Record<string, unknown>;
};

export type ParityResponse = {
  count: number;
  events: ParityEvent[];
  latest_mismatches?: ParityMismatchRow[];
};

export type ReseedStartResponse = {
  job_id: string;
  status: "running";
};

export type ReseedStatusResponse = {
  job_id?: string;
  status: "running" | "ok" | "error";
  rule_set_id?: string | null;
  already_loaded?: boolean;
  error?: string;
};
