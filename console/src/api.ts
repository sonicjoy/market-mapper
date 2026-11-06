import type {
  ChatResponse,
  Meta,
  ParityResponse,
  ReseedStartResponse,
  ReseedStatusResponse,
  ReviewCard,
  ReviewHistoryRow,
  RulesResponse,
  VerifyResponse,
} from "./types";
import { DEFAULT_RULES_KIND } from "./lib/rulesQuery";
import { isStreamDrop } from "./lib/streamDrop";

type ChatBody = {
  message: string;
  conversation_id?: string;
  page_context?: Record<string, unknown>;
};

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    const nested = detail?.detail;
    const message = nested?.message ?? nested?.reason_code ?? nested;
    throw new Error(typeof message === "string" ? message : `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const getMeta = () => api<Meta>("/meta");

export const postChat = (body: ChatBody) =>
  api<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });

/** SSE first; one JSON /chat retry when the gateway resets the stream. */
export async function postChatWithFallback(
  body: ChatBody,
  onToken: (text: string) => void,
  onStatus?: (text: string) => void,
): Promise<ChatResponse> {
  try {
    return await postChatStream(body, onToken, onStatus);
  } catch (err) {
    if (!isStreamDrop(err)) throw err;
    onStatus?.("Connection dropped — retrying without the live stream…");
    return postChat(body);
  }
}

/** SSE chat turn: streams status + token events then resolves the final envelope. */
export async function postChatStream(
  body: ChatBody,
  onToken: (text: string) => void,
  onStatus?: (text: string) => void,
): Promise<ChatResponse> {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalPayload: ChatResponse | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const block of parts) {
      const event = /event:\s*(\w+)/.exec(block)?.[1];
      const dataLine = block
        .split("\n")
        .find((l) => l.startsWith("data:"));
      if (!dataLine) continue;
      const raw = dataLine.slice(5).trim();
      if (raw === "[DONE]") continue;
      const data = JSON.parse(raw) as Record<string, unknown>;
      if ((event === "status" || event === "error") && typeof data.text === "string") {
        onStatus?.(data.text);
      }
      if (event === "token" && typeof data.text === "string") onToken(data.text);
      if (event === "final") finalPayload = data as unknown as ChatResponse;
    }
  }
  if (!finalPayload) throw new Error("stream ended without final event");
  return finalPayload;
}

export const verifyEntry = (body: {
  paste: string;
  provided_name?: string;
  note?: string;
  acknowledge_live_warning?: boolean;
  disambiguation_label?: string;
  league?: string;
}) =>
  api<VerifyResponse>("/entry/verify", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const verifyStructuredAlias = (body: {
  league: string;
  sportsbook: string;
  alias_value: string;
  provided_name: string;
  entity_type?: string;
  alias_kind?: string;
  canonical_key?: string;
  note?: string;
  acknowledge_shadow?: boolean;
  remove?: boolean;
}) =>
  api<VerifyResponse>("/entry/alias/verify", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const submitEntry = (preview_token: string) =>
  api<ReviewCard>("/entry/submit", {
    method: "POST",
    body: JSON.stringify({ preview_token }),
  });

export const verifyLeague = (body: Record<string, unknown>) =>
  api<Record<string, unknown>>("/entry/league/verify", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const submitLeague = (body: Record<string, unknown>, idempotencyKey?: string) =>
  api<ReviewCard>("/entry/league/submit", {
    method: "POST",
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {},
    body: JSON.stringify(body),
  });

export const verifyMarketRule = (body: Record<string, unknown>) =>
  api<Record<string, unknown>>("/entry/market-rule/verify", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const submitMarketRule = (
  body: Record<string, unknown>,
  idempotencyKey?: string,
) =>
  api<ReviewCard>("/entry/market-rule/submit", {
    method: "POST",
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {},
    body: JSON.stringify(body),
  });

export const suggestMarketRules = (body: {
  league: string;
  optic_league_id?: string;
  sport?: string;
  sportsbooks?: string[];
  template_league?: string | null;
}) =>
  api<{
    ok: boolean;
    warnings: string[];
    source: string | null;
    suggestions: {
      id: string;
      label: string;
      selected_default: boolean;
      pin: Record<string, unknown>;
    }[];
  }>("/entry/market-rule/suggest", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const harvestLeagueExchangeId = (body: {
  league: string;
  sport?: string;
  optic_league_id: string;
  sportsbook: string;
  fixture_horizon_hours?: number | null;
}) =>
  api<{
    ok: boolean;
    book: string;
    evidence: boolean;
    source?: string;
    settings?: Record<string, unknown>;
    note?: string;
    error?: string;
    fixture_count?: number;
  }>("/entry/league/harvest-id", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const suggestAliases = (body: {
  league: string;
  sport?: string;
  optic_league_id: string;
  fixture_horizon_hours?: number;
}) =>
  api<{
    ok: boolean;
    warnings: string[];
    suggestions: {
      id: string;
      label: string;
      selected_default: boolean;
      payload: Record<string, unknown>;
    }[];
  }>("/entry/alias/suggest", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const verifyBatch = (body: {
  entity_aliases?: Record<string, unknown>[];
  leagues?: Record<string, unknown>[];
  market_rules?: Record<string, unknown>[];
  note?: string;
  acknowledge_shadow?: boolean;
}) =>
  api<{
    ok: boolean;
    blockers: string[];
    warnings: string[];
    preview: {
      summary: string;
      evidence?: string[];
      cards?: { venue: string; transform: string; optic: string; label: string }[];
    } | null;
    preview_token: string | null;
    payload?: Record<string, unknown>;
  }>("/entry/batch/verify", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const submitBatch = (preview_token: string) =>
  api<ReviewCard>("/entry/batch/submit", {
    method: "POST",
    body: JSON.stringify({ preview_token }),
  });

export const listReview = () => api<ReviewCard[]>("/review");

export const listReviewRecent = (limit = 10) =>
  api<ReviewHistoryRow[]>(`/review/recent?limit=${limit}`);

export const getProposedLeagues = (ref?: string) =>
  api<import("./types").ProposedView>(
    `/console/proposed/leagues${ref ? `?ref=${encodeURIComponent(ref)}` : ""}`,
  );

export const trimProposedItems = (ref: string, drop: { kind: string; key: string }[]) =>
  api<ReviewCard>(`/console/proposed/${ref}/items`, {
    method: "POST",
    body: JSON.stringify({ drop }),
  });

export const listCoverageFixtures = (opts: {
  league?: string;
  sport?: string;
  q?: string;
  phase?: string;
  limit?: number;
  offset?: number;
} = {}) => {
  const params = new URLSearchParams();
  if (opts.league) params.set("league", opts.league);
  if (opts.sport) params.set("sport", opts.sport);
  if (opts.q) params.set("q", opts.q);
  if (opts.phase) params.set("phase", opts.phase);
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  const q = params.toString();
  return api<{ count: number; fixtures: import("./types").CoverageFixture[]; disclaimer?: string }>(
    `/console/coverage/fixtures${q ? `?${q}` : ""}`,
  );
};

export const getCoverageFixture = (fixtureId: string, league?: string) => {
  const q = league ? `?league=${encodeURIComponent(league)}` : "";
  return api<import("./types").CoverageFixture>(
    `/console/coverage/fixtures/${encodeURIComponent(fixtureId)}${q}`,
  );
};

export const listMissingSymbols = (opts: {
  platform?: string;
  league?: string;
  sport?: string;
  scope?: string;
  market_group?: string;
  contract_type?: string[];
  kickoff_from?: string;
  kickoff_to?: string;
  q?: string;
  sort?: string;
  dir?: string;
  limit?: number;
  offset?: number;
  refresh?: boolean;
} = {}) => {
  const params = new URLSearchParams();
  if (opts.platform) params.set("platform", opts.platform);
  if (opts.league) params.set("league", opts.league);
  if (opts.sport) params.set("sport", opts.sport);
  if (opts.scope) params.set("scope", opts.scope);
  if (opts.market_group) params.set("market_group", opts.market_group);
  for (const value of opts.contract_type ?? []) params.append("contract_type", value);
  if (opts.kickoff_from) params.set("kickoff_from", opts.kickoff_from);
  if (opts.kickoff_to) params.set("kickoff_to", opts.kickoff_to);
  if (opts.q) params.set("q", opts.q);
  if (opts.sort) params.set("sort", opts.sort);
  if (opts.dir) params.set("dir", opts.dir);
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  if (opts.refresh) params.set("refresh", "true");
  const q = params.toString();
  return api<{
    count: number;
    rows: import("./types").MissingSymbolRow[];
    market_options?: import("./types").MissingMarketOption[];
    cache_age_sec?: number | null;
    refreshed_at?: string | null;
    error?: string | null;
    note?: string;
    bq_project?: string | null;
    local_path?: string | null;
  }>(`/console/missing-symbols${q ? `?${q}` : ""}`);
};

export const listUnmappedLegs = (opts: {
  platform?: string;
  league?: string;
  sport?: string;
  q?: string;
  phase?: string;
  sort?: string;
  dir?: string;
  limit?: number;
  offset?: number;
} = {}) => {
  const params = new URLSearchParams();
  if (opts.platform) params.set("platform", opts.platform);
  if (opts.league) params.set("league", opts.league);
  if (opts.sport) params.set("sport", opts.sport);
  if (opts.q) params.set("q", opts.q);
  if (opts.phase) params.set("phase", opts.phase);
  if (opts.sort) params.set("sort", opts.sort);
  if (opts.dir) params.set("dir", opts.dir);
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  const q = params.toString();
  return api<{ count: number; rows: import("./types").UnmappedLegRow[]; error?: string | null }>(
    `/console/unmapped-legs${q ? `?${q}` : ""}`,
  );
};

export const getUnmappedLegWhy = (row: {
  platform: string;
  key: string;
  platform_leg_description?: string;
  league?: string | null;
  fixture?: string | null;
  sport?: string | null;
  market_group?: string;
  contract_type?: string;
  crypto_ids?: string[];
}) => {
  const params = new URLSearchParams({ platform: row.platform, key: row.key });
  if (row.platform_leg_description) params.set("description", row.platform_leg_description);
  if (row.league) params.set("league", row.league);
  if (row.fixture) params.set("fixture", row.fixture);
  if (row.sport) params.set("sport", row.sport);
  if (row.market_group) params.set("market_group", row.market_group);
  if (row.contract_type) params.set("contract_type", row.contract_type);
  if (row.crypto_ids?.length) params.set("crypto_ids", row.crypto_ids.join(","));
  return api<{
    platform: string;
    key: string;
    has_fixes: boolean;
    mappable_items: import("./types").MappableItem[];
    reasons: import("./types").UnmappedWhyReason[];
  }>(`/console/unmapped-legs/why?${params.toString()}`);
};

export const lookupCatalog = (params: {
  sportsbook: string;
  source_market_id: string;
  source_selection_id?: string;
}) => {
  const q = new URLSearchParams({
    sportsbook: params.sportsbook,
    source_market_id: params.source_market_id,
    source_selection_id: params.source_selection_id ?? "",
  });
  return api<{
    rfq_key: string;
    winner: Record<string, unknown> | null;
    candidates: Record<string, unknown>[];
    candidate_count: number;
    in_rank_window: boolean | null;
    lookup_note: string | null;
    resolved_source_market_id: string;
    resolved_source_selection_id: string;
  }>(`/console/catalog/lookup?${q.toString()}`);
};

export const publishCatalogOverride = (body: {
  sportsbook: string;
  game_id: string;
  market_id: string;
  selection: string;
  source_market_id: string;
  source_selection_id?: string;
  selection_line?: string;
  points?: number;
  selection_points?: number;
  grouping_key?: string;
  mapping_source?: string;
  reason: string;
  active?: boolean;
}) =>
  api<{
    job_id: string;
    status: string;
    message: string;
    poll_url: string;
    steps: Record<string, unknown>;
    lookup?: Record<string, unknown> | null;
  }>("/console/catalog/override", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getCatalogOverrideJob = (jobId: string) =>
  api<{
    job_id: string;
    status: string;
    message: string;
    active: boolean;
    steps: Record<string, unknown>;
    lookup?: {
      winner?: Record<string, unknown> | null;
      candidates?: Record<string, unknown>[];
    } | null;
  }>(`/console/catalog/override/jobs/${jobId}`);

export const stageUnmappedLeg = (body: {
  platform: string;
  key: string;
  item_ids: string[];
  platform_leg_description?: string;
  league?: string | null;
  fixture?: string | null;
  sport?: string | null;
  market_group?: string;
  contract_type?: string;
  crypto_ids?: string[];
}) =>
  api<{
    ok: boolean;
    error?: string;
    cart_items: Array<{
      kind: import("./cartStore").CartItemKind;
      label: string;
      payload: Record<string, unknown>;
    }>;
  }>("/console/unmapped-legs/stage", {
    method: "POST",
    body: JSON.stringify(body),
  });

export const combinePipelineReview = () =>
  api<ReviewCard[]>("/review/combine-pipeline", { method: "POST", body: "{}" });

export const getReview = (ref: string) => api<ReviewCard>(`/review/${ref}`);

export const approveReview = (ref: string) =>
  api<ReviewCard>(`/review/${ref}/approve`, { method: "POST", body: "{}" });

export const rejectReview = (ref: string, comment: string) =>
  api<ReviewCard>(`/review/${ref}/reject`, {
    method: "POST",
    body: JSON.stringify({ comment }),
  });

export const requestChangesReview = (ref: string, comment: string) =>
  api<ReviewCard>(`/review/${ref}/request-changes`, {
    method: "POST",
    body: JSON.stringify({ comment }),
  });

function appendAll(params: URLSearchParams, key: string, values?: string[]): void {
  for (const value of values ?? []) {
    if (value) params.append(key, value);
  }
}

export const searchRules = (
  q: string,
  kind = DEFAULT_RULES_KIND,
  opts: {
    limit?: number;
    offset?: number;
    league?: string[];
    sportsbook?: string[];
    canonical?: string[];
    action?: string[];
    sort?: string;
    dir?: string;
  } = {},
) => {
  const params = new URLSearchParams({
    q,
    kind,
    limit: String(opts.limit ?? 20),
    offset: String(opts.offset ?? 0),
  });
  appendAll(params, "league", opts.league);
  appendAll(params, "sportsbook", opts.sportsbook);
  appendAll(params, "canonical", opts.canonical);
  appendAll(params, "action", opts.action);
  if (opts.sort) {
    params.set("sort", opts.sort);
    if (opts.dir) params.set("dir", opts.dir);
  }
  return api<RulesResponse>(`/console/rules?${params.toString()}`);
};
export const listParity = () => api<ParityResponse>("/console/parity");

export const checkParity = () =>
  api<ParityResponse>("/console/parity/check", { method: "POST", body: "{}" });

export const startReseed = () =>
  api<ReseedStartResponse>("/console/parity/reseed", { method: "POST", body: "{}" });

export const reseedStatus = (jobId: string) =>
  api<ReseedStatusResponse>(`/console/parity/reseed/${jobId}`);
