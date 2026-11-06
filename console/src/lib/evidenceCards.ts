/** Group flat review evidence_refs into alias, book, and notes cards. */

export type EvidenceCardKind = "alias" | "notes" | "book";

export type EvidenceCardModel = {
  title: string;
  refs: string[];
  kind: EvidenceCardKind;
};

export type EvidenceFallback = {
  title: string;
  tokens: string[];
};

type AliasItem = {
  title: string;
  name: string;
  ids: Set<string>;
  usaCodes: Set<string>;
};

type RefParts = {
  head: string;
  mid: string;
  rest: string;
};

const BOOK_TITLES: Record<string, string> = {
  optic: "Optic",
  kalshi: "Kalshi",
  polymarket: "Polymarket",
  polymarket_usa: "Polymarket US",
  "crypto.com": "crypto.com",
  px: "ProphetX",
  novig: "Novig",
  underdog: "Underdog",
  dkex: "DraftKings Exchange",
  txodds: "TxODDS",
};
const BOOK_ORDER = [
  "optic",
  "kalshi",
  "polymarket",
  "polymarket_usa",
  "crypto.com",
  "px",
  "novig",
  "underdog",
  "dkex",
] as const;
const PIN_MIDS = new Set(["id", "prefix", "parser", "fixtures", "slug", "meta"]);

export function groupEvidenceCards(
  evidence: string[],
  aliasLines: string[],
  fallback?: EvidenceFallback,
): EvidenceCardModel[] {
  const aliases = resolveAliases(aliasLines, fallback);
  const refs = collapseSameMatchup(evidence);
  if (aliases.length === 0) return bookAndNotes(refs);
  if (aliases.length === 1) return singleAliasCards(aliases[0], refs);
  return multiAliasCards(aliases, refs);
}

function multiAliasCards(aliases: AliasItem[], evidence: string[]): EvidenceCardModel[] {
  const buckets = aliases.map(() => [] as string[]);
  const leftover: string[] = [];
  let current: number | null = null;
  for (const ref of evidence) {
    const owned = ownerIndexes(aliases, ref);
    if (owned.length) {
      for (const idx of owned) pushRef(buckets, idx, ref);
      current = owned[0] ?? null;
      continue;
    }
    if (current !== null && isSticky(ref)) {
      pushRef(buckets, current, ref);
      continue;
    }
    leftover.push(ref);
  }
  const fixtures = uniqueRefs([
    ...leftover.filter(isFixtureRef),
    ...buckets.flat().filter(isFixtureRef),
  ]);
  const notes = leftover.filter((ref) => keepAsNote(ref, fixtures.length));
  return [...aliasCardsWithSource(aliases, buckets, leftover), ...bookAndNotes(notes)];
}

function keepAsNote(ref: string, fixtureCount: number): boolean {
  if (isSharedSource(ref)) return false;
  return !(isFixtureRef(ref) && fixtureCount === 1);
}

function aliasCardsWithSource(
  aliases: AliasItem[],
  buckets: string[][],
  leftover: string[],
): EvidenceCardModel[] {
  const shared = uniqueRefs([
    ...leftover.filter(isSharedSource),
    ...buckets.flat().filter(isSharedSource),
  ]);
  const cards: EvidenceCardModel[] = [];
  for (const [idx, alias] of aliases.entries()) {
    const bucket = buckets[idx] ?? [];
    const own = bucket.filter((ref) => !isSharedSource(ref));
    const refs = uniqueRefs(withUsaCodes(alias, [...shared, ...own]));
    if (!refs.length) continue;
    cards.push({ title: alias.title, refs, kind: "alias" });
  }
  return cards;
}

function uniqueRefs(refs: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const ref of refs) {
    if (seen.has(ref)) continue;
    seen.add(ref);
    out.push(ref);
  }
  return out;
}

function collapseSameMatchup(refs: string[]): string[] {
  const best = new Map<string, { score: number; idx: number }>();
  const drop = new Set<number>();
  refs.forEach((ref, idx) => {
    if (!isFixtureRef(ref)) return;
    const label = fixtureLabel(ref).toLowerCase();
    if (!label.includes(" vs ")) return;
    const score = fixtureIdScore(ref);
    const prev = best.get(label);
    if (!prev) {
      best.set(label, { score, idx });
      return;
    }
    if (score > prev.score) {
      drop.add(prev.idx);
      best.set(label, { score, idx });
    } else drop.add(idx);
  });
  return refs.filter((_, idx) => !drop.has(idx));
}

function fixtureIdScore(ref: string): number {
  const id = (refParts(ref).rest.split(":")[0] ?? "").trim();
  return /^[0-9A-Fa-f]{16}$/.test(id) ? 2 : 0;
}

function resolveAliases(aliasLines: string[], fallback?: EvidenceFallback): AliasItem[] {
  const parsed = aliasLines
    .map(parseAliasLine)
    .filter((item): item is AliasItem => item !== null);
  if (parsed.length) return parsed;
  if (!fallback?.title) return [];
  const ids = new Set(
    fallback.tokens.map((token) => token.trim().toLowerCase()).filter(Boolean),
  );
  return [{ title: fallback.title, name: fallback.title, ids, usaCodes: new Set() }];
}

function parseAliasLine(line: string): AliasItem | null {
  const text = line.replace(/^[-+~]\s+/, "");
  const arrow = text.indexOf(" → ");
  if (arrow < 0) return null;
  const rawName = text
    .slice(arrow + 3)
    .replace(/\s*\([^)]*\)\s*$/, "")
    .trim();
  if (!rawName) return null;
  const pins = pinParts(text.slice(0, arrow));
  const ids = new Set(pins.values.map((value) => value.toLowerCase()));
  return { title: rawName, name: displayName(rawName), ids, usaCodes: pins.usaCodes };
}

function displayName(raw: string): string {
  const match = /^([A-Z][A-Z0-9]{1,5}) (.+)$/.exec(raw);
  if (!match) return raw;
  const key = match[1];
  if (key.length < 3 && !/\d/.test(key)) return raw;
  return match[2];
}

function pinParts(left: string): { values: string[]; usaCodes: Set<string> } {
  const body = left.replace(/^Map\s+/i, "");
  const values: string[] = [];
  const usaCodes = new Set<string>();
  for (const part of body.split(/,\s+/)) {
    const match =
      /^(Optic|Kalshi|crypto\.com|polymarket_usa|Polymarket)\s+(.+)$/i.exec(part.trim());
    if (!match?.[2]) continue;
    const value = stripPinLabel(match[2].trim());
    values.push(value);
    if (match[1].toLowerCase() === "polymarket_usa") usaCodes.add(value.toLowerCase());
  }
  return { values, usaCodes };
}

function withUsaCodes(alias: AliasItem, refs: string[]): string[] {
  const extra: string[] = [];
  for (const code of alias.usaCodes) {
    const want = `polymarket_usa:code:${code}`;
    if (!refs.some((ref) => ref.toLowerCase() === want)) extra.push(want);
  }
  const shown = alias.name.trim();
  if (
    alias.usaCodes.size &&
    shown &&
    !refs.some((ref) => ref.toLowerCase().startsWith("polymarket_usa:name:"))
  ) {
    extra.push(`polymarket_usa:name:${shown}`);
  }
  return extra.length ? [...extra, ...refs] : refs;
}

function ownerIndexes(aliases: AliasItem[], ref: string): number[] {
  return aliases.flatMap((item, idx) => (aliasOwnsRef(item, ref) ? [idx] : []));
}

function stripPinLabel(value: string): string {
  return value.replace(/\s+\([^)]*\)\s*$/, "").trim();
}

function aliasOwnsRef(alias: AliasItem, ref: string): boolean {
  if (isFixtureRef(ref)) return fixtureOwnedBy(alias, ref);
  if (isKalshiTitle(ref) || isKalshiMarket(ref)) return kalshiOwnedBy(alias, ref);
  if (isKalshiGap(ref)) return tickerOwnedBy(alias, ref);
  const usa = usaInnerCode(ref);
  if (usa && alias.ids.has(usa)) return true;
  const value = refValue(ref);
  if (!value) return false;
  if (isNameRef(ref)) return value.toLowerCase() === alias.name.toLowerCase();
  return alias.ids.has(value.toLowerCase());
}

function usaInnerCode(ref: string): string {
  const { head, mid, rest } = refParts(ref);
  if (head !== "gap" || mid !== "usa-inner") return "";
  const bits = rest.split(":");
  return (bits[bits.length - 1] ?? "").toLowerCase();
}

function fixtureOwnedBy(alias: AliasItem, ref: string): boolean {
  const label = fixtureLabel(ref).toLowerCase();
  return fixtureNames(alias).some((name) => name.length >= 3 && label.includes(name));
}

function fixtureNames(alias: AliasItem): string[] {
  const stripped = alias.title.replace(/^[A-Z][A-Z0-9]{1,5}\s+/, "").trim();
  return [alias.name, alias.title, stripped]
    .map((name) => name.toLowerCase())
    .filter((name, idx, all) => name.length >= 3 && all.indexOf(name) === idx);
}

function fixtureLabel(ref: string): string {
  const rest = refParts(ref).rest;
  const cut = rest.indexOf(":");
  const after = cut > 0 ? rest.slice(cut + 1).trim() : "";
  if (after.includes(" vs ")) return after;
  return rest.includes(" vs ") ? rest.trim() : after;
}

function isLabeledFixture(ref: string): boolean {
  return isFixtureRef(ref) && fixtureLabel(ref).includes(" vs ");
}

function refValue(ref: string): string {
  const parts = refParts(ref);
  if (parts.head === "crypto_id") return ref.trim().slice("crypto_id:".length);
  if (parts.head === "optic" && parts.mid === "competitor") {
    return (parts.rest.split(":")[0] ?? "").trim();
  }
  if (parts.head === "crypto" && parts.mid === "symbol") return symbolCryptoId(parts.rest);
  return parts.rest;
}

function isNameRef(ref: string): boolean {
  const parts = refParts(ref);
  return (parts.head === "optic" || parts.head === "crypto") && parts.mid === "name";
}

function isSticky(ref: string): boolean {
  const parts = refParts(ref);
  if (isLabeledFixture(ref)) return false;
  if (parts.head === "polymarket_usa" && parts.mid !== "code") return true;
  return (
    isFixtureRef(ref) ||
    (parts.head === "crypto" && parts.mid === "symbol") ||
    isSharedSource(ref)
  );
}

function isFixtureRef(ref: string): boolean {
  const parts = refParts(ref);
  return parts.head === "optic" && parts.mid === "fixture";
}

function isSharedSource(ref: string): boolean {
  const parts = refParts(ref);
  if (parts.head === "gap") {
    if (usaInnerCode(ref) !== "") return false;
    return !isKalshiGap(ref);
  }
  if (parts.head === "source") return true;
  if (parts.head === "optic" && parts.mid === "league") return true;
  return (
    parts.head === "polymarket" &&
    ["question", "description", "market", "slug", "outcome"].includes(parts.mid)
  );
}

function isKalshiTitle(ref: string): boolean {
  const { head, mid } = refParts(ref);
  return head === "kalshi" && mid === "title";
}

function isKalshiMarket(ref: string): boolean {
  const { head, mid } = refParts(ref);
  return head === "kalshi" && mid === "market";
}

function isKalshiGap(ref: string): boolean {
  const { head, mid, rest } = refParts(ref);
  if (head !== "gap") return false;
  const ticker = (rest || mid).toUpperCase();
  return ticker.startsWith("KX");
}

function kalshiOwnedBy(alias: AliasItem, ref: string): boolean {
  const rest = refParts(ref).rest.toLowerCase();
  if (tickerOwnedBy(alias, rest)) return true;
  return textOwnedBy(alias, rest);
}

function tickerOwnedBy(alias: AliasItem, hay: string): boolean {
  const text = hay.toLowerCase();
  for (const id of alias.ids) {
    if (id.length >= 3 && text.includes(id)) return true;
  }
  return false;
}

function textOwnedBy(alias: AliasItem, label: string): boolean {
  return fixtureNames(alias).some((name) => name.length >= 3 && label.includes(name));
}

function refParts(ref: string): RefParts {
  const bits = ref.trim().split(":");
  return {
    head: (bits[0] ?? "").toLowerCase(),
    mid: (bits[1] ?? "").toLowerCase(),
    rest: bits.slice(2).join(":"),
  };
}

function pushRef(buckets: string[][], idx: number, ref: string): void {
  const bucket = buckets[idx];
  if (bucket) bucket.push(ref);
}

function notesCard(refs: string[]): EvidenceCardModel {
  return { title: "Notes", refs, kind: "notes" };
}

function singleAliasCards(
  only: AliasItem | undefined,
  evidence: string[],
): EvidenceCardModel[] {
  if (!only) return [];
  const { kept, pins } = peelLeaguePins(evidence);
  if (!kept.length) {
    return [{ title: only.title, refs: withUsaCodes(only, evidence), kind: "alias" }];
  }
  return [
    { title: only.title, refs: withUsaCodes(only, kept), kind: "alias" },
    ...bookAndNotes(pins),
  ];
}

function peelLeaguePins(refs: string[]): { kept: string[]; pins: string[] } {
  const kept: string[] = [];
  const pins: string[] = [];
  for (const ref of refs) {
    if (leaguePinBook(ref)) pins.push(ref);
    else kept.push(ref);
  }
  return { kept, pins };
}

function leaguePinBook(ref: string): string | null {
  const { head, mid } = refParts(ref);
  if (head === "skip" && mid) return normalizeBook(mid);
  if (PIN_MIDS.has(mid)) return normalizeBook(head);
  return null;
}

function normalizeBook(head: string): string {
  return head === "crypto" ? "crypto.com" : head;
}

function bookAndNotes(refs: string[]): EvidenceCardModel[] {
  if (!refs.length) return [];
  const buckets = new Map<string, string[]>();
  const notes: string[] = [];
  for (const ref of refs) {
    const book = leaguePinBook(ref);
    if (book) {
      const list = buckets.get(book) ?? [];
      list.push(ref);
      buckets.set(book, list);
    } else notes.push(ref);
  }
  const cards: EvidenceCardModel[] = BOOK_ORDER.filter((book) => buckets.has(book)).map(
    (book) => ({
      title: BOOK_TITLES[book] ?? book,
      refs: buckets.get(book) ?? [],
      kind: "book" as const,
    }),
  );
  for (const [book, bookRefs] of buckets) {
    if ((BOOK_ORDER as readonly string[]).includes(book)) continue;
    cards.push({ title: BOOK_TITLES[book] ?? book, refs: bookRefs, kind: "book" });
  }
  if (notes.length) cards.push(notesCard(notes));
  return cards;
}

const REF_LABELS: Record<string, string> = {
  "optic:competitor": "Optic competitor",
  "ai:needle": "AI searched for",
  "optic:name": "Name",
  "optic:abbr": "Abbr",
  "optic:id": "Optic league",
  "optic:fixtures": "Fixtures",
  "crypto:name": "Name",
  "crypto:title": "Title",
  "kalshi:title": "Kalshi",
  "kalshi:market_title": "Market title",
  "kalshi:yes_sub_title": "yes_sub_title",
  "kalshi:rules_primary": "rules_primary",
  "kalshi:market": "Kalshi market",
  "kalshi:code": "Kalshi",
  "kalshi:id": "Kalshi",
  "kalshi:parser": "Parser",
  "polymarket:question": "Question",
  "polymarket:description": "Description",
  "polymarket:market": "Market",
  "polymarket:slug": "Slug",
  "polymarket:name": "Name",
  "polymarket:outcome": "Outcome",
  "polymarket_usa:ticker": "Polymarket US ticker",
  "polymarket_usa:code": "Polymarket US code",
  "polymarket_usa:name": "Polymarket US name",
  "polymarket_usa:title": "Polymarket US title",
  "polymarket_usa:match": "Polymarket US",
  "polymarket_usa:inner": "Polymarket US inner",
  "source:sport": "Sport",
  "source:league": "League",
  "source:date": "Date",
  "optic:league": "Optic league",
  "underdog:ticker": "Underdog UDX",
  "underdog:league": "Underdog venue",
  "dkex:ticker": "DKEX symbol",
  "dkex:participant": "DKEX participant",
};

export function evidenceLines(card: EvidenceCardModel): string[] {
  const seen = new Set<string>();
  const lines: string[] = [];
  for (const ref of card.refs) {
    if (duplicateName(card, ref)) continue;
    const line = displayEvidenceRef(ref);
    if (isFixtureRef(ref) && seen.has(line)) continue;
    if (isFixtureRef(ref)) seen.add(line);
    lines.push(line);
  }
  return lines;
}

export function displayEvidenceRef(ref: string): string {
  const trimmed = ref.trim();
  const bits = trimmed.split(":");
  const head = (bits[0] ?? "").toLowerCase();
  const mid = (bits[1] ?? "").toLowerCase();
  const rest = bits.slice(2).join(":");
  if (head === "skip") return rest || bits[1] || mid;
  if (head === "optic" && mid === "fixture") return fixtureLine(rest);
  if (head === "optic" && mid === "competitor") return competitorLine(rest);
  if (head === "crypto_id") return `crypto.com: ${trimmed.slice("crypto_id:".length)}`;
  if (head === "crypto" && mid === "symbol") return symbolLine(rest);
  if (head === "txodds") return txoddsLine(mid, rest);
  if (head === "gap" && mid === "usa-inner") return usaInnerLine(rest);
  if (head === "gap") return `Gap: ${trimmed.slice("gap:".length)}`;
  if (head === "note") return `Note: ${trimmed.slice("note:".length)}`;
  const label = REF_LABELS[`${head}:${mid}`] ?? titleLabel(mid || head);
  if (rest) return `${label}: ${rest}`;
  const after = trimmed.slice((bits[0] ?? "").length + 1);
  return after ? `${label}: ${after}` : label || trimmed;
}

/** txodds:team:<id>:<name> | txodds:unverified:<why> | txodds:name-unchecked (live_evidence_txodds.py). */
function txoddsLine(mid: string, rest: string): string {
  if (mid === "team") {
    const cut = rest.indexOf(":");
    if (cut > 0) return `TxODDS team: ${rest.slice(cut + 1).trim()} (${rest.slice(0, cut).trim()})`;
    return `TxODDS team: ${rest}`;
  }
  if (mid === "unverified") return `TxODDS team list not readable here (${rest || "unknown"}): pin not checked`;
  if (mid === "name-unchecked") return "TxODDS name not checked: this canonical has no name";
  return rest ? `TxODDS ${mid}: ${rest}` : `TxODDS ${mid}`;
}

function competitorLine(rest: string): string {
  const cut = rest.indexOf(":");
  if (cut > 0) {
    const oid = rest.slice(0, cut).trim();
    const name = rest.slice(cut + 1).trim();
    if (name) return `Optic competitor: ${name} (${oid})`;
  }
  return rest ? `Optic competitor: ${rest}` : "Optic competitor";
}

// crypto:symbol is tagged `{cryptoId}:{symbol}`; older refs carry the bare symbol.
function symbolCryptoId(rest: string): string {
  const cut = rest.indexOf(":");
  return cut > 0 ? rest.slice(0, cut).trim() : "";
}

function symbolLine(rest: string): string {
  const cut = rest.indexOf(":");
  const symbol = (cut > 0 ? rest.slice(cut + 1) : rest).trim();
  return symbol ? `Symbol: ${symbol}` : "Symbol";
}

function usaInnerLine(rest: string): string {
  const [league, code] = rest.split(":");
  if (code && league) return `Polymarket US: ${code} (${league.replace(/_/g, " ")})`;
  return rest ? `Polymarket US: ${rest}` : "Polymarket US";
}

function fixtureLine(rest: string): string {
  const cut = rest.indexOf(":");
  if (cut > 0) {
    const detail = rest.slice(cut + 1).trim();
    if (detail) return `Fixture: ${detail}`;
  }
  return rest ? `Fixture: ${rest}` : "Fixture";
}

function duplicateName(card: EvidenceCardModel, ref: string): boolean {
  const { head, mid, rest } = refParts(ref);
  if (mid !== "name" || (head !== "optic" && head !== "crypto")) return false;
  const title = card.title.toLowerCase();
  const name = rest.toLowerCase();
  if (!name) return false;
  return title === name || title.endsWith(` ${name}`);
}

function titleLabel(raw: string): string {
  if (raw === "crypto.com") return "crypto.com";
  return raw.replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}
