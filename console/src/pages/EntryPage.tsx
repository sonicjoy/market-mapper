import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";

import { publishEntryFields } from "../consoleView";
import {
  submitEntry,
  submitLeague,
  submitMarketRule,
  harvestLeagueExchangeId,
  suggestAliases,
  suggestMarketRules,
  verifyEntry,
  verifyLeague,
  verifyMarketRule,
  verifyStructuredAlias,
} from "../api";
import { addCartItem, cartLeagueSlugs, upsertCartItem, useCart } from "../cartStore";
import { BookChipToggle } from "../components/BookChipToggle";
import { RulePreviewCards, type RuleCard } from "../components/RulePreviewCards";
import { EnumSelect } from "../components/EnumSelect";
import { LiveAckCheckbox } from "../components/LiveAckCheckbox";
import { PageHeader } from "../components/PageHeader";
import {
  booksFromExchanges,
  exchangePayload,
  leagueMetaFromExchanges,
  type BookPinState,
} from "../lib/leagueEntryBooks";
import {
  CANONICAL_MARKET_TYPES,
  ALIAS_ENFORCEMENTS,
  DEFAULT_FIXTURE_HORIZON_HOURS,
  MAX_FIXTURE_HORIZON_HOURS,
  MARKET_ACTIONS,
  SPORTS,
  ALIAS_SPORTSBOOKS,
  SPORTSBOOKS,
  aliasKindFor,
  defaultParserProfile,
  harvestLoadingLabel,
  sourceKeyHint,
  sourceKeyTypeFor,
  sourceLeagueIdLabel,
} from "../entryEnums";
import { leagueFormPrefill } from "../lib/tipLeaguePrefill";
import { GATEWAY_DROP_NOTE, isGatewayDrop } from "../lib/gatewayDrop";
import { useIdempotencyKey } from "../lib/idempotency";
import { matchEntityType, resolveEntityType } from "../lib/matchEntityType";
import { formatMarketRuleCartLabel, pinsFromPayload } from "../lib/marketRules";
import { isProposedReturnTo } from "../lib/proposedViewState";
import { LIVE_BANNER } from "../lib/sotCopy";
import type { EntryLocationState, ReviewCard, VerifyResponse } from "../types";
import { useTipLeagues } from "../useTipLeagues";

type Tab = "alias" | "league" | "market";

type LeagueVerify = {
  ok: boolean;
  blockers: string[];
  warnings: string[];
  preview: {
    summary: string;
    league_label: string;
    optic_league_id: string;
    exchange_count: number;
  } | null;
  payload?: Record<string, unknown>;
};

type MarketVerify = {
  ok: boolean;
  blockers: string[];
  warnings: string[];
  pending_league?: boolean;
  preview: {
    summary: string;
    league_label: string;
    rule_count: number;
    cards?: RuleCard[];
  } | null;
  payload?: Record<string, unknown>;
};

const TABS: { id: Tab; label: string }[] = [
  { id: "alias", label: "Pin alias" },
  { id: "league", label: "Add league" },
  { id: "market", label: "Market rule" },
];

const FROM_RULES_BANNER =
  "Editing from Rules - submit creates a new proposal (append-only snapshot).";
const FROM_CART_BANNER =
  "Editing a cart item. Verify, then Update cart item to replace that row.";

function cartSaveLabel(cartItemId?: string, mode?: "create" | "amend" | "remove" | "cart"): string {
  if (cartItemId) return "Update cart item";
  if (mode === "amend") return "Add amendment to cart";
  if (mode === "remove") return "Add removal to cart";
  return "Add to cart";
}

type EditorMode = "create" | "amend" | "remove" | "cart";

function EditorModeStatus({ mode }: { mode: EditorMode }) {
  switch (mode) {
    case "create":
      return (
        <span
          role="status"
          className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-300"
        >
          Create
        </span>
      );
    case "amend":
      return (
        <span
          role="status"
          className="rounded bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-950 dark:text-amber-200"
        >
          Amend
        </span>
      );
    case "remove":
      return (
        <span
          role="status"
          className="rounded bg-red-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-900 dark:bg-red-950 dark:text-red-200"
        >
          Remove
        </span>
      );
    case "cart":
      return (
        <span
          role="status"
          className="rounded bg-brand-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide dark:bg-brand-950"
        >
          Cart draft
        </span>
      );
    default: {
      const _exhaustive: never = mode;
      return _exhaustive;
    }
  }
}

function TabBar({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <div className="mb-4 flex gap-1 border-b border-slate-200 dark:border-slate-700">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          className={`px-3 py-1.5 text-sm ${
            tab === t.id
              ? "border-b-2 border-brand-600 font-medium text-brand-800 dark:text-brand-200"
              : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
          }`}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

function SubmittedLink({ refId }: { refId: string }) {
  return (
    <p className="text-sm text-slate-700 dark:text-slate-300">
      Submitted - waiting for checker.{" "}
      <Link className="text-brand-700 underline dark:text-brand-300" to={`/review/${refId}`}>
        Open review
      </Link>
    </p>
  );
}

function AliasTab({
  initialPaste,
  initialNote,
  structured,
  removeMode = false,
  cartItemId,
  saveLabel,
}: {
  initialPaste: string;
  initialNote: string;
  cartItemId?: string;
  saveLabel?: string;
  removeMode?: boolean;
  structured: {
    league: string;
    sportsbook: string;
    code: string;
    entity_name: string;
    entity_type: string;
    canonical_key: string;
    alias_kind: string;
  } | null;
}) {
  const structuredMode = structured != null;
  const tipLeagues = useTipLeagues();
  const qc = useQueryClient();
  const cart = useCart();
  const cartLeagues = useMemo(() => cartLeagueSlugs(), [cart]);
  const [paste, setPaste] = useState(initialPaste);
  const [name, setName] = useState(structured?.entity_name ?? "");
  const [note, setNote] = useState(initialNote);
  const [ack, setAck] = useState(false);
  const [ackShadow, setAckShadow] = useState(false);
  const [choice, setChoice] = useState("");
  const [league, setLeague] = useState(structured?.league ?? "");
  const [sportsbook, setSportsbook] = useState(structured?.sportsbook ?? "");
  const [code, setCode] = useState(structured?.code ?? "");
  const [entityType, setEntityType] = useState(structured?.entity_type ?? "team");
  const [canonicalKey, setCanonicalKey] = useState(structured?.canonical_key ?? "");
  const [aliasKind, setAliasKind] = useState(
    structured?.alias_kind || aliasKindFor(structured?.sportsbook ?? "optic"),
  );
  const [result, setResult] = useState<VerifyResponse | null>(null);
  const [submittedRef, setSubmittedRef] = useState<string | null>(null);
  const [submitNote, setSubmitNote] = useState<string | null>(null);
  const [addedToCart, setAddedToCart] = useState(false);

  useEffect(() => {
    setPaste(initialPaste);
    setNote(initialNote);
    setAddedToCart(false);
    if (structured) {
      setLeague(structured.league);
      setSportsbook(structured.sportsbook);
      setCode(structured.code);
      setName(structured.entity_name);
      setEntityType(structured.entity_type || matchEntityType(structured.league));
      setCanonicalKey(structured.canonical_key);
      setAliasKind(structured.alias_kind || aliasKindFor(structured.sportsbook));
    }
  }, [initialPaste, initialNote, structured]);

  const leagueOptions = useMemo(() => {
    const tip = tipLeagues.data ?? [];
    const merged = [...new Set([...cartLeagues, ...tip])].sort((a, b) =>
      a.localeCompare(b),
    );
    if (league && !merged.includes(league)) return [league, ...merged];
    return merged;
  }, [tipLeagues.data, cartLeagues, league]);

  const verify = useMutation({
    mutationFn: () =>
      structuredMode
        ? verifyStructuredAlias({
            league,
            sportsbook,
            alias_value: code,
            provided_name: name,
            entity_type: entityType,
            alias_kind: aliasKind,
            canonical_key: canonicalKey || undefined,
            note: note || undefined,
            acknowledge_shadow: ackShadow,
            remove: removeMode,
          })
        : verifyEntry({
            paste,
            provided_name: name || undefined,
            note: note || undefined,
            acknowledge_live_warning: ack,
            disambiguation_label: choice || undefined,
            league: league || undefined,
          }),
    onSuccess: (res) => {
      setResult(res);
      setAddedToCart(false);
    },
  });

  // The preview token is the idempotency key server-side, so a retry with the
  // same token returns the existing card instead of creating a second one.
  const submit = useMutation({
    mutationFn: () => {
      if (!result?.preview_token) throw new Error("missing preview");
      return submitEntry(result.preview_token);
    },
    onMutate: () => setSubmitNote(null),
    onSuccess: (card: ReviewCard) => {
      setSubmittedRef(card.ref);
      void qc.invalidateQueries({ queryKey: ["review"] });
    },
    onError: (err) => {
      void qc.invalidateQueries({ queryKey: ["review"] });
      if (isGatewayDrop(err)) setSubmitNote(GATEWAY_DROP_NOTE);
    },
  });

  const addToCart = () => {
    if (!result?.ok || !result.payload) return;
    const label = result.preview?.summary.replace(/\*\*/g, "") ?? "Alias pin";
    upsertCartItem(cartItemId, { kind: "entity_alias", label, payload: result.payload });
    setAddedToCart(true);
  };

  return (
    <div className="card max-w-2xl space-y-3">
      {structuredMode ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="al-league">
                League
              </label>
              <EnumSelect
                id="al-league"
                value={league}
                options={leagueOptions}
                allowEmpty
                emptyLabel={tipLeagues.isLoading ? "Loading leagues..." : "Select league..."}
                onChange={(v) => {
                  setLeague(v);
                  if (!structured?.canonical_key) setEntityType(matchEntityType(v));
                  setResult(null);
                }}
              />
            </div>
            <div>
              <label className="label" htmlFor="al-book">
                Sportsbook
              </label>
              <EnumSelect
                id="al-book"
                value={sportsbook}
                options={ALIAS_SPORTSBOOKS}
                allowEmpty
                emptyLabel="Select sportsbook..."
                onChange={(v) => {
                  setSportsbook(v);
                  setAliasKind(aliasKindFor(v));
                  setResult(null);
                }}
              />
            </div>
            <div>
              <label className="label" htmlFor="al-code">
                Code / alias value
              </label>
              <input
                id="al-code"
                className="input font-mono"
                value={code}
                onChange={(e) => {
                  setCode(e.target.value);
                  setResult(null);
                }}
              />
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Exact exchange string ({aliasKind} for {sportsbook || "sportsbook"}).
              </p>
            </div>
            <div>
              <label className="label" htmlFor="al-type">
                Entity type
              </label>
              <p id="al-type" className="input bg-slate-50 font-mono text-sm dark:bg-slate-900">
                {entityType}
              </p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Match competitor bucket (team / fighter). Player is for props only.
              </p>
            </div>
          </div>
          <div>
            <label className="label" htmlFor="al-key">
              Canonical key
            </label>
            <input
              id="al-key"
              className="input font-mono"
              value={canonicalKey}
              onChange={(e) => {
                setCanonicalKey(e.target.value);
                setResult(null);
              }}
            />
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Existing entity key, or leave blank to create from the name.
            </p>
          </div>
        </>
      ) : (
        <>
          <div>
            <label className="label" htmlFor="paste">
              Paste crypto id / Optic id
            </label>
            <textarea
              id="paste"
              className="input min-h-[80px] font-mono text-sm"
              value={paste}
              onChange={(e) => {
                setPaste(e.target.value);
                setResult(null);
              }}
              placeholder="Optic competitor id or crypto.com id"
            />
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Kalshi tickers are not alias pins: Kalshi maps from its own typed fields.
            </p>
          </div>
          <div>
            <label className="label" htmlFor="al-paste-league">
              League
            </label>
            <EnumSelect
              id="al-paste-league"
              value={league}
              options={leagueOptions}
              allowEmpty
              emptyLabel={tipLeagues.isLoading ? "Loading leagues..." : "Select league..."}
              onChange={(v) => {
                setLeague(v);
                setResult(null);
              }}
            />
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Required for Optic competitor ids and crypto ids.
            </p>
          </div>
        </>
      )}
      <div>
        <label className="label" htmlFor="name">
          Entity name
        </label>
        <input
          id="name"
          className="input"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setResult(null);
          }}
          placeholder="Mainz 05"
        />
      </div>
      <div>
        <label className="label" htmlFor="note">
          Note (optional)
        </label>
        <input
          id="note"
          className="input"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>
      {structuredMode ? (
        <LiveAckCheckbox checked={ackShadow} onChange={setAckShadow} />
      ) : result?.needs_live_ack ? (
        <label className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-300">
          <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
          <span>Acknowledge live-evidence warning if shown</span>
        </label>
      ) : null}
      {result?.disambiguation_choices?.length ? (
        <div>
          <label className="label" htmlFor="choice">
            Disambiguation
          </label>
          <select
            id="choice"
            className="input"
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
          >
            <option value="">Select...</option>
            {result.disambiguation_choices.map((c) => (
              <option key={c.label} value={c.label}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={
            verify.isPending ||
            (structuredMode
              ? !league.trim() || !sportsbook.trim() || !code.trim() || !name.trim()
              : !paste.trim())
          }
          onClick={() => verify.mutate()}
        >
          Verify
        </button>
        {result?.ok && result.payload ? (
          <>
            <button type="button" className="btn-primary" onClick={addToCart}>
              {saveLabel ?? cartSaveLabel(cartItemId)}
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={submit.isPending}
              onClick={() => submit.mutate()}
            >
              Submit alone
            </button>
          </>
        ) : null}
      </div>
      {result?.blockers?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-red-700">
          {result.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      ) : null}
      {result?.warnings?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-amber-800 dark:text-amber-200">
          {result.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      {result?.preview && (
        <div className="notice-brand text-sm">
          <div className="font-medium">Preview</div>
          <p className="mt-1">{result.preview.summary.replace(/\*\*/g, "")}</p>
          {result.preview.evidence?.length ? (
            <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs">
              {result.preview.evidence.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
      {addedToCart ? (
        <p className="text-sm text-brand-800 dark:text-brand-200">
          {cartItemId ? "Updated cart item." : "Added to cart."}{" "}
          <Link className="underline" to="/cart">
            Open cart
          </Link>
        </p>
      ) : null}
      {submittedRef && <SubmittedLink refId={submittedRef} />}
      {submitNote && <p className="text-sm text-amber-600">{submitNote}</p>}
      {!submitNote && (verify.error || submit.error) && (
        <p className="text-sm text-red-600">{(verify.error || submit.error)?.message}</p>
      )}
    </div>
  );
}

function LeagueTab({
  initialLeague,
  initialNote,
  initialSport,
  initialOptic,
  initialFixture,
  initialFixtureHorizon,
  initialExchanges,
  initialFocusSportsbook,
  initialEntityType,
  initialAliasEnforcement,
  initialRunshopEnabled,
  cartItemId,
  saveLabel,
}: {
  initialLeague: string;
  initialNote: string;
  initialSport?: string;
  initialOptic?: string;
  initialFixture?: string;
  initialFixtureHorizon?: number;
  initialExchanges?: Record<string, unknown>[];
  initialFocusSportsbook?: string;
  initialEntityType?: string;
  initialAliasEnforcement?: string;
  initialRunshopEnabled?: boolean;
  cartItemId?: string;
  saveLabel?: string;
}) {
  const tipLeagues = useTipLeagues();
  const qc = useQueryClient();
  const seeded = leagueFormPrefill({
    slug: initialLeague,
    tip: tipLeagues.bySlug[initialLeague.trim()],
    explicitSport: initialSport,
    explicitOptic: initialOptic,
    explicitHorizon: initialFixtureHorizon,
    explicitExchanges: initialExchanges,
  });
  const [league, setLeague] = useState(initialLeague);
  const [sport, setSport] = useState(seeded.sport ?? initialSport ?? "");
  const [opticLeagueId, setOpticLeagueId] = useState(
    seeded.opticLeagueId ?? initialOptic ?? "",
  );
  const [entityType, setEntityType] = useState<"team" | "fighter">(() =>
    resolveEntityType(
      initialEntityType,
      initialLeague,
      initialSport ?? "",
      leagueMetaFromExchanges(initialExchanges).entity_type,
    ),
  );
  const [aliasEnforcement, setAliasEnforcement] = useState("raise");
  const [runshopEnabled, setRunshopEnabled] = useState(false);
  const [fixtureSource] = useState(initialFixture ?? "api");
  const [fixtureHorizonHours, setFixtureHorizonHours] = useState<number | "">(
    seeded.fixtureHorizonHours ??
      initialFixtureHorizon ??
      DEFAULT_FIXTURE_HORIZON_HOURS,
  );
  const [books, setBooks] = useState<Record<string, BookPinState>>(() =>
    booksFromExchanges(seeded.exchanges ?? initialExchanges),
  );
  const [cloneFrom, setCloneFrom] = useState("");
  const [note, setNote] = useState(initialNote);
  const [ackShadow, setAckShadow] = useState(false);
  const [result, setResult] = useState<LeagueVerify | null>(null);
  const [submittedRef, setSubmittedRef] = useState<string | null>(null);
  const [submitNote, setSubmitNote] = useState<string | null>(null);
  const [addedToCart, setAddedToCart] = useState(false);
  const idem = useIdempotencyKey();
  const [marketSuggestions, setMarketSuggestions] = useState<
    { id: string; label: string; pin: Record<string, unknown>; selected: boolean }[]
  >([]);
  const [marketSuggestWarnings, setMarketSuggestWarnings] = useState<string[]>([]);
  const [aliasSuggestions, setAliasSuggestions] = useState<
    { id: string; label: string; payload: Record<string, unknown>; selected: boolean }[]
  >([]);
  const [aliasSuggestWarnings, setAliasSuggestWarnings] = useState<string[]>([]);
  const [suggestMsg, setSuggestMsg] = useState<string | null>(null);
  const [harvestingBooks, setHarvestingBooks] = useState<Set<string>>(() => new Set());
  const [harvestNotes, setHarvestNotes] = useState<Record<string, string>>({});
  const harvestAttemptedRef = useRef<Record<string, boolean>>({});
  const harvestGenerationRef = useRef<Record<string, number>>({});
  const prevOpticHarvestRef = useRef("");

  useEffect(() => {
    setLeague(initialLeague);
    setNote(initialNote);
    setAddedToCart(false);
    const meta = leagueMetaFromExchanges(initialExchanges);
    setEntityType(
      resolveEntityType(
        initialEntityType,
        initialLeague,
        initialSport ?? "",
        meta.entity_type,
      ),
    );
    setAliasEnforcement(
      (initialAliasEnforcement ?? "").trim() || meta.alias_enforcement,
    );
    setRunshopEnabled(initialRunshopEnabled ?? meta.runshop_enabled);
    const next = leagueFormPrefill({
      slug: initialLeague,
      tip: tipLeagues.bySlug[initialLeague.trim()],
      explicitSport: initialSport,
      explicitOptic: initialOptic,
      explicitHorizon: initialFixtureHorizon,
      explicitExchanges: initialExchanges,
    });
    setSport(next.sport ?? initialSport ?? "");
    setOpticLeagueId(next.opticLeagueId ?? initialOptic ?? "");
    setFixtureHorizonHours(
      next.fixtureHorizonHours ??
        initialFixtureHorizon ??
        DEFAULT_FIXTURE_HORIZON_HOURS,
    );
    setBooks(booksFromExchanges(next.exchanges ?? initialExchanges));
  }, [
    initialLeague,
    initialNote,
    initialSport,
    initialOptic,
    initialFixtureHorizon,
    initialExchanges,
    initialEntityType,
    initialAliasEnforcement,
    initialRunshopEnabled,
  ]);

  useEffect(() => {
    const next = leagueFormPrefill({
      slug: league,
      tip: tipLeagues.bySlug[league.trim()],
      explicitSport: initialSport,
      explicitOptic: initialOptic,
      explicitHorizon: initialFixtureHorizon,
      explicitExchanges: initialExchanges,
    });
    if (next.sport != null) setSport(next.sport);
    if (next.opticLeagueId != null) setOpticLeagueId(next.opticLeagueId);
    if (next.fixtureHorizonHours != null && fixtureHorizonHours !== "") {
      setFixtureHorizonHours(next.fixtureHorizonHours);
    }
    if (next.exchanges != null) {
      const loaded = booksFromExchanges(next.exchanges);
      setBooks(loaded);
      setHarvestNotes((prev) => {
        const out = { ...prev };
        for (const book of SPORTSBOOKS) {
          if (loaded[book]?.source_league_id?.trim()) {
            delete out[book];
          }
        }
        return out;
      });
    }
    // fixtureHorizonHours omitted: empty input must stick until the slug changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    league,
    tipLeagues.bySlug,
    initialSport,
    initialOptic,
    initialFixtureHorizon,
    initialExchanges,
  ]);

  useEffect(() => {
    const book = (initialFocusSportsbook || "").trim();
    if (!book) return;
    const id = book === "optic" ? "lg-optic" : `lg-book-${book}`;
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("ring-2", "ring-brand-400", "ring-offset-2");
    const timer = window.setTimeout(() => {
      el.classList.remove("ring-2", "ring-brand-400", "ring-offset-2");
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [initialFocusSportsbook]);

  useEffect(() => {
    const optic = opticLeagueId.trim();
    if (optic === prevOpticHarvestRef.current) return;
    prevOpticHarvestRef.current = optic;
    if (!optic) return;
    for (const book of SPORTSBOOKS) {
      harvestAttemptedRef.current[book] = false;
    }
    setHarvestNotes({});
  }, [opticLeagueId]);

  useEffect(() => {
    if (!opticLeagueId.trim() || !league.trim()) return;
    for (const book of SPORTSBOOKS) {
      const pin = books[book];
      if (!pin?.enabled || pin.source_league_id.trim() || harvestingBooks.has(book)) continue;
      if (harvestAttemptedRef.current[book]) continue;
      void runHarvestBook(book, pin);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opticLeagueId, league, books, harvestingBooks]);

  const cloneOptions = useMemo(() => {
    const tip = tipLeagues.data ?? [];
    if (cloneFrom && !tip.includes(cloneFrom)) return [cloneFrom, ...tip];
    return tip;
  }, [tipLeagues.data, cloneFrom]);

  function buildBody(): Record<string, unknown> {
    const exchanges = Object.entries(books)
      .filter(([, pin]) => pin.enabled)
      .map(([sportsbook, pin]) =>
        exchangePayload(sportsbook, pin, { sport: sport.trim() }),
      );
    return {
      league: league.trim(),
      sport: sport.trim(),
      optic_league_id: opticLeagueId.trim(),
      fixture_source: fixtureSource.trim() || "api",
      fixture_horizon_hours:
        typeof fixtureHorizonHours === "number" ? fixtureHorizonHours : null,
      entity_type: entityType,
      alias_enforcement: aliasEnforcement,
      runshop_enabled: runshopEnabled,
      exchanges,
      clone_market_rules_from: cloneFrom.trim() || null,
      note: note.trim() || null,
      acknowledge_shadow: ackShadow,
    };
  }

  const verify = useMutation({
    mutationFn: async () => (await verifyLeague(buildBody())) as LeagueVerify,
    onSuccess: (data) => {
      setResult(data);
      setSubmittedRef(null);
      setAddedToCart(false);
    },
  });

  const submit = useMutation({
    mutationFn: async () => submitLeague(buildBody(), idem.current()),
    onMutate: () => setSubmitNote(null),
    onSuccess: (card: ReviewCard) => {
      idem.reset();
      setSubmittedRef(card.ref);
      void qc.invalidateQueries({ queryKey: ["review"] });
    },
    onError: (err) => {
      void qc.invalidateQueries({ queryKey: ["review"] });
      if (isGatewayDrop(err)) setSubmitNote(GATEWAY_DROP_NOTE);
    },
  });

  const addToCart = () => {
    if (!result?.ok || !result.payload) return;
    const label = result.preview?.summary.replace(/\*\*/g, "") ?? `League ${league}`;
    upsertCartItem(cartItemId, { kind: "mapping_league", label, payload: result.payload });
    setAddedToCart(true);
  };

  const enabledBooks = useMemo(
    () => Object.entries(books).filter(([, pin]) => pin.enabled).map(([b]) => b),
    [books],
  );

  const runHarvestBook = async (book: string, pin: BookPinState) => {
    if (!pin.enabled || pin.source_league_id.trim() || harvestAttemptedRef.current[book]) {
      return;
    }
    if (!league.trim() || !opticLeagueId.trim()) {
      return;
    }
    const generation = (harvestGenerationRef.current[book] ?? 0) + 1;
    harvestGenerationRef.current[book] = generation;
    harvestAttemptedRef.current[book] = true;
    setHarvestingBooks((prev) => new Set(prev).add(book));
    try {
      const res = await harvestLeagueExchangeId({
        league: league.trim(),
        sport: sport.trim(),
        optic_league_id: opticLeagueId.trim(),
        sportsbook: book,
        fixture_horizon_hours:
          typeof fixtureHorizonHours === "number" ? fixtureHorizonHours : null,
      });
      if (harvestGenerationRef.current[book] !== generation) {
        return;
      }
      if (res.evidence && res.source) {
        setBooks((prev) => {
          const current = prev[book] ?? pin;
          if (!current.enabled || current.source_league_id.trim()) {
            return prev;
          }
          return {
            ...prev,
            [book]: {
              ...current,
              enabled: true,
              source_league_id: res.source ?? "",
              settings: { ...current.settings, ...(res.settings ?? {}) },
            },
          };
        });
        setHarvestNotes((prev) => {
          const out = { ...prev };
          delete out[book];
          return out;
        });
      } else {
        const harvestMsg = res.note ?? res.error;
        if (harvestMsg) {
          setBooks((prev) => {
            if (prev[book]?.source_league_id?.trim()) {
              return prev;
            }
            setHarvestNotes((n) => ({ ...n, [book]: harvestMsg }));
            return prev;
          });
        }
      }
    } catch (err) {
      if (harvestGenerationRef.current[book] !== generation) {
        return;
      }
      const message = err instanceof Error ? err.message : "Harvest failed";
      setBooks((prev) => {
        if (prev[book]?.source_league_id?.trim()) {
          return prev;
        }
        setHarvestNotes((n) => ({ ...n, [book]: message }));
        return prev;
      });
    } finally {
      setHarvestingBooks((prev) => {
        if (harvestGenerationRef.current[book] !== generation) return prev;
        if (!prev.has(book)) return prev;
        const out = new Set(prev);
        out.delete(book);
        return out;
      });
    }
  };

  const toggleBook = async (book: string, pin: BookPinState, next: boolean) => {
    if (!next) {
      harvestGenerationRef.current[book] = (harvestGenerationRef.current[book] ?? 0) + 1;
      harvestAttemptedRef.current[book] = false;
      setHarvestNotes((prev) => {
        const out = { ...prev };
        delete out[book];
        return out;
      });
      setBooks((prev) => ({
        ...prev,
        [book]: { ...pin, enabled: false },
      }));
      setResult(null);
      return;
    }
    const enabledPin = { ...pin, enabled: true };
    setBooks((prev) => ({
      ...prev,
      [book]: enabledPin,
    }));
    setResult(null);
    await runHarvestBook(book, enabledPin);
  };

  const suggestMarkets = useMutation({
    mutationFn: () =>
      suggestMarketRules({
        league: league.trim(),
        optic_league_id: opticLeagueId.trim(),
        sport: sport.trim(),
        sportsbooks: enabledBooks,
        template_league: cloneFrom.trim() || null,
      }),
    onSuccess: (res) => {
      setMarketSuggestWarnings(res.warnings ?? []);
      setMarketSuggestions(
        (res.suggestions ?? []).map((s) => ({
          id: s.id,
          label: s.label,
          pin: s.pin,
          selected: s.selected_default !== false,
        })),
      );
      setSuggestMsg(null);
    },
    onError: (err: Error) => setSuggestMsg(err.message),
  });

  const suggestAliasPins = useMutation({
    mutationFn: () =>
      suggestAliases({
        league: league.trim(),
        sport: sport.trim(),
        optic_league_id: opticLeagueId.trim(),
        ...(typeof fixtureHorizonHours === "number"
          ? { fixture_horizon_hours: fixtureHorizonHours }
          : {}),
      }),
    onSuccess: (res) => {
      setAliasSuggestWarnings(res.warnings ?? []);
      setAliasSuggestions(
        (res.suggestions ?? []).map((s) => ({
          id: s.id,
          label: s.label,
          payload: s.payload,
          selected: s.selected_default !== false,
        })),
      );
      setSuggestMsg(null);
    },
    onError: (err: Error) => setSuggestMsg(err.message),
  });

  const addSelectedMarketsToCart = () => {
    const pins = marketSuggestions.filter((s) => s.selected).map((s) => s.pin);
    if (!league.trim() || !pins.length) return;
    addCartItem({
      kind: "mapping_market_rules",
      label: formatMarketRuleCartLabel(league.trim(), pins),
      payload: { kind: "mapping_market_rules", league: league.trim(), rules: pins },
    });
    setSuggestMsg(`Added ${pins.length} market rule(s) to cart.`);
  };

  const addSelectedAliasesToCart = () => {
    const selected = aliasSuggestions.filter((s) => s.selected);
    for (const s of selected) {
      addCartItem({
        kind: "entity_alias",
        label: s.label,
        payload: s.payload,
      });
    }
    if (selected.length) setSuggestMsg(`Added ${selected.length} alias pin(s) to cart.`);
  };

  const bookList = useMemo(() => {
    const known = new Set<string>(SPORTSBOOKS);
    const extra = Object.keys(books).filter((b) => !known.has(b));
    return [...SPORTSBOOKS, ...extra.sort()];
  }, [books]);

  return (
    <div className="card max-w-2xl space-y-3">
      <div className="notice-amber text-xs">
        {LIVE_BANNER}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="lg-league">
            League slug
          </label>
          <input
            id="lg-league"
            className="input font-mono"
            value={league}
            onChange={(e) => {
              setLeague(e.target.value);
              setResult(null);
            }}
            placeholder="bundesliga"
          />
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">New internal league key (snake_case).</p>
        </div>
        <div>
          <label className="label" htmlFor="lg-sport">
            Sport
          </label>
          <EnumSelect
            id="lg-sport"
            value={sport}
            options={SPORTS}
            allowEmpty
            emptyLabel="Select sport..."
            onChange={(v) => {
              setSport(v);
              setEntityType(matchEntityType(league, v));
              setResult(null);
            }}
          />
        </div>
        <div>
          <label className="label" htmlFor="lg-optic">
            Optic league id
          </label>
          <input
            id="lg-optic"
            className="input font-mono"
            value={opticLeagueId}
            onChange={(e) => setOpticLeagueId(e.target.value)}
            placeholder="germany_-_bundesliga"
          />
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">Exact Optic league id string.</p>
        </div>
        <div>
          <label className="label" htmlFor="lg-horizon">
            Fixture horizon (hours)
          </label>
          <input
            id="lg-horizon"
            type="number"
            min={1}
            max={MAX_FIXTURE_HORIZON_HOURS}
            step={1}
            className="input font-mono"
            value={fixtureHorizonHours}
            onChange={(e) => {
              const raw = e.target.value;
              if (raw === "") {
                setFixtureHorizonHours("");
                setResult(null);
                return;
              }
              const n = Number(raw);
              if (!Number.isFinite(n) || n <= 0 || n > MAX_FIXTURE_HORIZON_HOURS) return;
              setFixtureHorizonHours(n);
              setResult(null);
            }}
          />
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Optic fetch window. Mapper default is {DEFAULT_FIXTURE_HORIZON_HOURS} (7 days).
          </p>
        </div>
        <div>
          <label className="label" htmlFor="lg-entity-type">
            Entity type
          </label>
          <p id="lg-entity-type" className="input bg-slate-50 font-mono text-sm dark:bg-slate-900">
            {entityType}
          </p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            From sport: tennis match sides are team; UFC/boxing/MMA are fighter.
          </p>
        </div>
        <div>
          <label className="label" htmlFor="lg-alias-enforcement">
            Alias enforcement
          </label>
          <EnumSelect
            id="lg-alias-enforcement"
            value={aliasEnforcement}
            options={ALIAS_ENFORCEMENTS}
            onChange={(v) => {
              setAliasEnforcement(v);
              setResult(null);
            }}
          />
        </div>
        <div className="sm:col-span-2">
          <label className="flex items-center gap-2 text-sm text-slate-800 dark:text-slate-200">
            <input
              type="checkbox"
              checked={runshopEnabled}
              onChange={(e) => {
                setRunshopEnabled(e.target.checked);
                setResult(null);
              }}
            />
            Enable Runshop fetch for this league
          </label>
        </div>
      </div>

      <fieldset className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
        <legend className="px-1 text-xs font-medium text-slate-700 dark:text-slate-300">Exchanges</legend>
        <p className="text-xs text-slate-500 dark:text-slate-400">Enable books for this league. Parser profiles are set automatically.</p>
        {bookList.map((book) => {
          const pin = books[book] ?? {
            enabled: false,
            source_league_id: "",
            parser_profile: defaultParserProfile(book),
            settings: {},
          };
          return (
            <div
              key={book}
              id={`lg-book-${book}`}
              className="space-y-1 rounded border border-slate-100 p-2 dark:border-slate-800"
            >
              <BookChipToggle
                book={book}
                enabled={pin.enabled}
                title={pin.enabled ? "Enabled — click to disable" : "Disabled — click to enable"}
                label={`${pin.enabled ? "Disable" : "Enable"} ${book}`}
                onToggle={(next) => {
                  void toggleBook(book, pin, next);
                }}
              />
              {pin.enabled ? (
                <div>
                  <label className="label" htmlFor={`lg-src-${book}`}>
                    {sourceLeagueIdLabel(book)}
                  </label>
                  {harvestingBooks.has(book) ? (
                    <p className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                      <span
                        className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700 dark:border-slate-600 dark:border-t-slate-200"
                        aria-hidden="true"
                      />
                      {harvestLoadingLabel(book)}
                    </p>
                  ) : null}
                  <input
                    id={`lg-src-${book}`}
                    className="input font-mono"
                    value={pin.source_league_id}
                    disabled={harvestingBooks.has(book)}
                    onChange={(e) => {
                      setBooks((prev) => ({
                        ...prev,
                        [book]: { ...pin, source_league_id: e.target.value },
                      }));
                      setResult(null);
                    }}
                    placeholder={
                      book === "polymarket_usa"
                        ? "cfb"
                        : book === "underdog" || book === "dkex"
                          ? "NFL"
                          : ""
                    }
                  />
                  {harvestNotes[book] ? (
                    <p className="mt-1 text-xs text-amber-800 dark:text-amber-200">
                      {harvestNotes[book]}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </fieldset>

      <div>
        <label className="label" htmlFor="lg-clone">
          Clone market rules from (optional)
        </label>
        <EnumSelect
          id="lg-clone"
          value={cloneFrom}
          options={cloneOptions}
          allowEmpty
          emptyLabel={tipLeagues.isLoading ? "Loading leagues..." : "None"}
          onChange={(v) => {
            setCloneFrom(v);
            setResult(null);
          }}
        />
      </div>
      <div>
        <label className="label" htmlFor="lg-note">
          Note (optional)
        </label>
        <input
          id="lg-note"
          className="input"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>

      <fieldset className="space-y-2 rounded-md border border-slate-200 p-3 dark:border-slate-700">
        <legend className="px-1 text-xs font-medium text-slate-700 dark:text-slate-300">Auto-suggest (no agent)</legend>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Prefer Add league to cart first, then add suggested markets/aliases to the same cart and submit once.
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-ghost"
            disabled={
              suggestMarkets.isPending || !league.trim() || enabledBooks.length === 0
            }
            onClick={() => suggestMarkets.mutate()}
          >
            Suggest market rules
          </button>
          <button
            type="button"
            className="btn-ghost"
            disabled={
              suggestAliasPins.isPending || !league.trim() || !opticLeagueId.trim()
            }
            onClick={() => suggestAliasPins.mutate()}
          >
            Suggest aliases from Optic
          </button>
        </div>
        {marketSuggestWarnings.length ? (
          <ul className="list-disc pl-5 text-xs text-amber-800 dark:text-amber-200">
            {marketSuggestWarnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : null}
        {marketSuggestions.length ? (
          <div className="space-y-1">
            <div className="text-xs font-medium text-slate-700 dark:text-slate-300">Market suggestions</div>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-slate-100 p-2 dark:border-slate-800">
              {marketSuggestions.map((s) => (
                <label key={s.id} className="flex items-start gap-2 text-xs text-slate-800 dark:text-slate-200">
                  <input
                    type="checkbox"
                    checked={s.selected}
                    onChange={(e) =>
                      setMarketSuggestions((prev) =>
                        prev.map((x) =>
                          x.id === s.id ? { ...x, selected: e.target.checked } : x,
                        ),
                      )
                    }
                  />
                  <span className="font-mono">{s.label}</span>
                </label>
              ))}
            </div>
            <button type="button" className="btn-primary" onClick={addSelectedMarketsToCart}>
              Add selected markets to cart
            </button>
          </div>
        ) : null}
        {aliasSuggestWarnings.length ? (
          <ul className="list-disc pl-5 text-xs text-amber-800 dark:text-amber-200">
            {aliasSuggestWarnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : null}
        {aliasSuggestions.length ? (
          <div className="space-y-1">
            <div className="text-xs font-medium text-slate-700 dark:text-slate-300">Alias suggestions</div>
            <div className="max-h-40 space-y-1 overflow-y-auto rounded border border-slate-100 p-2 dark:border-slate-800">
              {aliasSuggestions.map((s) => (
                <label key={s.id} className="flex items-start gap-2 text-xs text-slate-800 dark:text-slate-200">
                  <input
                    type="checkbox"
                    checked={s.selected}
                    onChange={(e) =>
                      setAliasSuggestions((prev) =>
                        prev.map((x) =>
                          x.id === s.id ? { ...x, selected: e.target.checked } : x,
                        ),
                      )
                    }
                  />
                  <span>{s.label}</span>
                </label>
              ))}
            </div>
            <button type="button" className="btn-primary" onClick={addSelectedAliasesToCart}>
              Add selected aliases to cart
            </button>
          </div>
        ) : null}
        {suggestMsg ? <p className="text-xs text-brand-800 dark:text-brand-200">{suggestMsg}</p> : null}
        {(suggestMarkets.error || suggestAliasPins.error) && (
          <p className="text-xs text-red-600">
            {(suggestMarkets.error || suggestAliasPins.error)?.message}
          </p>
        )}
      </fieldset>

      <LiveAckCheckbox checked={ackShadow} onChange={setAckShadow} />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={verify.isPending || !league.trim() || !sport.trim() || !opticLeagueId.trim()}
          onClick={() => verify.mutate()}
        >
          Verify
        </button>
        {result?.ok && result.payload ? (
          <>
            <button type="button" className="btn-primary" onClick={addToCart}>
              {saveLabel ?? cartSaveLabel(cartItemId)}
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={submit.isPending}
              onClick={() => submit.mutate()}
            >
              Submit alone
            </button>
          </>
        ) : null}
      </div>

      {result?.blockers?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-red-700">
          {result.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      ) : null}
      {result?.warnings?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-amber-800 dark:text-amber-200">
          {result.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      {result?.preview && (
        <div className="notice-brand text-sm">
          <div className="font-medium">Preview</div>
          <p className="mt-1">{result.preview.summary.replace(/\*\*/g, "")}</p>
          <p className="mt-1 text-xs text-brand-800 dark:text-brand-200">
            {result.preview.league_label} · optic {result.preview.optic_league_id} ·{" "}
            {result.preview.exchange_count} exchange(s)
          </p>
        </div>
      )}

      {addedToCart ? (
        <p className="text-sm text-brand-800 dark:text-brand-200">
          {cartItemId ? "Updated cart item." : "Added to cart."}{" "}
          <Link className="underline" to="/cart">
            Open cart
          </Link>
        </p>
      ) : null}

      {submittedRef && <SubmittedLink refId={submittedRef} />}
      {submitNote && <p className="text-sm text-amber-600">{submitNote}</p>}

      {!submitNote && (verify.error || submit.error) && (
        <p className="text-sm text-red-600">{(verify.error || submit.error)?.message}</p>
      )}
    </div>
  );
}

function MarketRuleTab({
  initialLeague,
  initialSportsbook,
  initialNote,
  initialSourceKey,
  initialAction,
  initialCanonical,
  initialSourceKeyType,
  initialMatchOperator,
  initialLineOffset,
  initialYesSide,
  initialSideSwap,
  initialOfficialDescription,
  initialCitationUrl,
  cartItemId,
  saveLabel,
}: {
  initialLeague: string;
  initialSportsbook: string;
  initialNote: string;
  initialSourceKey?: string;
  initialAction?: string;
  initialCanonical?: string | null;
  initialSourceKeyType?: string;
  initialMatchOperator?: string;
  initialLineOffset?: number | null;
  initialYesSide?: string | null;
  initialSideSwap?: boolean | null;
  initialOfficialDescription?: string | null;
  initialCitationUrl?: string | null;
  cartItemId?: string;
  saveLabel?: string;
}) {
  const tipLeagues = useTipLeagues();
  const qc = useQueryClient();
  const cart = useCart();
  const cartLeagues = useMemo(() => cartLeagueSlugs(), [cart]);
  const defaultBook = initialSportsbook || "optic";
  const [league, setLeague] = useState(initialLeague);
  const [sportsbook, setSportsbook] = useState(defaultBook);
  const [sourceKeyType, setSourceKeyType] = useState(
    initialSourceKeyType || sourceKeyTypeFor(defaultBook),
  );
  const [sourceKey, setSourceKey] = useState(initialSourceKey || "");
  const [action, setAction] = useState(initialAction || "map");
  const [canonicalMarketType, setCanonicalMarketType] = useState(initialCanonical || "");
  const [matchOperator, setMatchOperator] = useState(initialMatchOperator || "exact");
  const [lineOffset, setLineOffset] = useState(
    initialLineOffset == null ? "" : String(initialLineOffset),
  );
  const [yesSide, setYesSide] = useState(initialYesSide ?? "");
  const [sideSwap, setSideSwap] = useState<"" | "yes" | "no">(
    initialSideSwap == null ? "" : initialSideSwap ? "yes" : "no",
  );
  const [officialDescription, setOfficialDescription] = useState(initialOfficialDescription ?? "");
  const [citationUrl, setCitationUrl] = useState(initialCitationUrl ?? "");
  const [note, setNote] = useState(initialNote);
  const [ackShadow, setAckShadow] = useState(false);
  const [result, setResult] = useState<MarketVerify | null>(null);
  const [submittedRef, setSubmittedRef] = useState<string | null>(null);
  const [submitNote, setSubmitNote] = useState<string | null>(null);
  const [addedToCart, setAddedToCart] = useState(false);
  const idem = useIdempotencyKey();

  useEffect(() => {
    setLeague(initialLeague);
    setNote(initialNote);
    setAddedToCart(false);
    if (initialSportsbook) {
      setSportsbook(initialSportsbook);
      setSourceKeyType(initialSourceKeyType || sourceKeyTypeFor(initialSportsbook));
    }
    if (initialSourceKey != null) setSourceKey(initialSourceKey);
    if (initialAction) setAction(initialAction);
    if (initialCanonical != null) setCanonicalMarketType(initialCanonical || "");
    setMatchOperator(initialMatchOperator || "exact");
    setLineOffset(initialLineOffset == null ? "" : String(initialLineOffset));
    setYesSide(initialYesSide ?? "");
    setSideSwap(initialSideSwap == null ? "" : initialSideSwap ? "yes" : "no");
    setOfficialDescription(initialOfficialDescription ?? "");
    setCitationUrl(initialCitationUrl ?? "");
  }, [
    initialLeague,
    initialNote,
    initialSportsbook,
    initialSourceKey,
    initialAction,
    initialCanonical,
    initialSourceKeyType,
    initialMatchOperator,
    initialLineOffset,
    initialYesSide,
    initialSideSwap,
    initialOfficialDescription,
    initialCitationUrl,
  ]);

  const tipSet = useMemo(() => new Set(tipLeagues.data ?? []), [tipLeagues.data]);
  const pendingOnly = Boolean(league.trim()) && cartLeagues.includes(league.trim()) && !tipSet.has(league.trim());

  const leagueOptions = useMemo(() => {
    const tip = tipLeagues.data ?? [];
    const merged = [...new Set([...cartLeagues, ...tip])].sort((a, b) =>
      a.localeCompare(b),
    );
    if (league && !merged.includes(league)) return [league, ...merged];
    return merged;
  }, [tipLeagues.data, cartLeagues, league]);

  function buildBody(): Record<string, unknown> {
    return {
      league: league.trim(),
      sportsbook: sportsbook.trim(),
      source_key_type: sourceKeyType.trim(),
      source_key: sourceKey.trim(),
      action: action.trim(),
      canonical_market_type:
        action.trim() === "ignore" ? null : canonicalMarketType.trim() || null,
      match_operator: matchOperator || "exact",
      line_offset: lineOffset.trim() === "" ? null : Number(lineOffset),
      yes_side: yesSide.trim() || null,
      side_swap: sideSwap === "" ? null : sideSwap === "yes",
      official_description: officialDescription.trim() || null,
      citation_url: citationUrl.trim() || null,
      notes: note.trim() || null,
      note: note.trim() || null,
      acknowledge_shadow: ackShadow,
      pending_league_slugs: cartLeagues,
    };
  }

  const verify = useMutation({
    mutationFn: async () => (await verifyMarketRule(buildBody())) as MarketVerify,
    onSuccess: (data) => {
      setResult(data);
      setSubmittedRef(null);
      setAddedToCart(false);
    },
  });

  const submit = useMutation({
    mutationFn: async () => submitMarketRule(buildBody(), idem.current()),
    onMutate: () => setSubmitNote(null),
    onSuccess: (card: ReviewCard) => {
      idem.reset();
      setSubmittedRef(card.ref);
      void qc.invalidateQueries({ queryKey: ["review"] });
    },
    onError: (err) => {
      void qc.invalidateQueries({ queryKey: ["review"] });
      if (isGatewayDrop(err)) setSubmitNote(GATEWAY_DROP_NOTE);
    },
  });

  const addToCart = () => {
    if (!result?.ok || !result.payload) return;
    const fromCard = result.preview?.cards?.length === 1 ? result.preview.cards[0].label : "";
    const label = fromCard || formatMarketRuleCartLabel(league, pinsFromPayload(result.payload));
    upsertCartItem(cartItemId, {
      kind: "mapping_market_rules",
      label,
      payload: result.payload,
    });
    setAddedToCart(true);
  };

  const canVerify =
    league.trim() &&
    sportsbook.trim() &&
    sourceKey.trim() &&
    (action === "ignore" || Boolean(canonicalMarketType.trim()));

  return (
    <div className="card max-w-2xl space-y-3">
      <div className="notice-amber text-xs">
        {LIVE_BANNER}
      </div>
      <div>
        <label className="label" htmlFor="mr-league">
          League
        </label>
        <EnumSelect
          id="mr-league"
          value={league}
          options={leagueOptions}
          allowEmpty
          emptyLabel={tipLeagues.isLoading ? "Loading leagues..." : "Select league..."}
          onChange={(v) => {
            setLeague(v);
            setResult(null);
          }}
        />
        {pendingOnly ? (
          <p className="mt-1 text-xs text-amber-800 dark:text-amber-200">
            This league is only in your cart — use Add to cart, then submit the batch (Submit alone needs tip).
          </p>
        ) : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="mr-book">
            Sportsbook
          </label>
          <EnumSelect
            id="mr-book"
            value={sportsbook}
            options={SPORTSBOOKS}
            onChange={(v) => {
              setSportsbook(v);
              setSourceKeyType(sourceKeyTypeFor(v));
              setResult(null);
            }}
          />
        </div>
        <div>
          <label className="label" htmlFor="mr-action">
            Action
          </label>
          <EnumSelect
            id="mr-action"
            value={action}
            options={MARKET_ACTIONS}
            onChange={(v) => {
              setAction(v);
              if (v === "ignore") setCanonicalMarketType("");
              setResult(null);
            }}
          />
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="mr-key">
            Source key
          </label>
          <input
            id="mr-key"
            className="input font-mono"
            value={sourceKey}
            onChange={(e) => setSourceKey(e.target.value)}
            placeholder={sportsbook === "crypto.com" ? "Moneyline" : "moneyline"}
          />
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{sourceKeyHint(sportsbook)}</p>
        </div>
        <div>
          <label className="label" htmlFor="mr-offset">
            Line offset
          </label>
          <input
            id="mr-offset"
            className="input font-mono"
            value={lineOffset}
            onChange={(e) => {
              setLineOffset(e.target.value);
              setResult(null);
            }}
            placeholder="blank = none"
          />
        </div>
        <div>
          <label className="label" htmlFor="mr-yes">
            Yes side
          </label>
          <input
            id="mr-yes"
            className="input font-mono"
            value={yesSide}
            onChange={(e) => {
              setYesSide(e.target.value);
              setResult(null);
            }}
            placeholder="blank = none"
          />
        </div>
        <div>
          <label className="label" htmlFor="mr-swap">
            Side swap
          </label>
          <select
            id="mr-swap"
            className="input"
            value={sideSwap}
            onChange={(e) => {
              const value = e.target.value;
              setSideSwap(value === "yes" || value === "no" ? value : "");
              setResult(null);
            }}
          >
            <option value="">—</option>
            <option value="no">no</option>
            <option value="yes">yes</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="mr-op">
            Match
          </label>
          <select
            id="mr-op"
            className="input"
            value={matchOperator}
            onChange={(e) => {
              setMatchOperator(e.target.value);
              setResult(null);
            }}
          >
            <option value="exact">exact</option>
            <option value="prefix">prefix</option>
            <option value="suffix">suffix</option>
          </select>
        </div>
        {action === "map" ? (
          <div className="sm:col-span-2">
            <label className="label" htmlFor="mr-cmt">
              Canonical market type
            </label>
            <EnumSelect
              id="mr-cmt"
              value={canonicalMarketType}
              options={CANONICAL_MARKET_TYPES}
              allowEmpty
              emptyLabel="Select market type..."
              onChange={(v) => {
                setCanonicalMarketType(v);
                setResult(null);
              }}
            />
          </div>
        ) : null}
        <div className="sm:col-span-2">
          <label className="label" htmlFor="mr-official">
            Official description
          </label>
          <textarea
            id="mr-official"
            className="input min-h-16"
            value={officialDescription}
            onChange={(e) => {
              setOfficialDescription(e.target.value);
              setResult(null);
            }}
            placeholder="Venue text. Leave blank if you do not have it."
          />
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="mr-citation">
            Citation URL
          </label>
          <input
            id="mr-citation"
            className="input"
            value={citationUrl}
            onChange={(e) => {
              setCitationUrl(e.target.value);
              setResult(null);
            }}
            placeholder="https://"
          />
        </div>
      </div>
      <div>
        <label className="label" htmlFor="mr-note">
          Trader notes
        </label>
        <input
          id="mr-note"
          className="input"
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>

      <LiveAckCheckbox checked={ackShadow} onChange={setAckShadow} />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-primary"
          disabled={verify.isPending || !canVerify}
          onClick={() => verify.mutate()}
        >
          Verify
        </button>
        {result?.ok && result.payload ? (
          <>
            <button type="button" className="btn-primary" onClick={addToCart}>
              {saveLabel ?? cartSaveLabel(cartItemId)}
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={submit.isPending || pendingOnly || Boolean(result.pending_league)}
              title={
                pendingOnly || result.pending_league
                  ? "League not on tip — submit via Cart batch"
                  : undefined
              }
              onClick={() => submit.mutate()}
            >
              Submit alone
            </button>
          </>
        ) : null}
      </div>

      {result?.blockers?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-red-700">
          {result.blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      ) : null}
      {result?.warnings?.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-amber-800 dark:text-amber-200">
          {result.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      {result?.preview && (
        <div className="notice-brand text-sm">
          <div className="font-medium">Preview</div>
          <p className="mt-1">{result.preview.summary.replace(/\*\*/g, "")}</p>
          <RulePreviewCards cards={result.preview.cards} />
          <p className="mt-1 text-xs text-brand-800 dark:text-brand-200">
            {result.preview.league_label} - {result.preview.rule_count} rule(s)
          </p>
        </div>
      )}

      {addedToCart ? (
        <p className="text-sm text-brand-800 dark:text-brand-200">
          {cartItemId ? "Updated cart item." : "Added to cart."}{" "}
          <Link className="underline" to="/cart">
            Open cart
          </Link>
        </p>
      ) : null}

      {submittedRef && <SubmittedLink refId={submittedRef} />}
      {submitNote && <p className="text-sm text-amber-600">{submitNote}</p>}

      {!submitNote && (verify.error || submit.error) && (
        <p className="text-sm text-red-600">{(verify.error || submit.error)?.message}</p>
      )}
    </div>
  );
}

export function EntryPage() {
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const state = (location.state ?? {}) as EntryLocationState;
  const [tab, setTab] = useState<Tab>(state.tab ?? "alias");
  const modeParam = searchParams.get("mode");
  const mode: EditorMode = state.cartItemId
    ? "cart"
    : modeParam === "create"
      ? "create"
      : modeParam === "remove" || state.mode === "remove"
        ? "remove"
        : modeParam === "amend" || state.fromRules || state.mode === "amend"
          ? "amend"
          : "create";
  const returnTo = isProposedReturnTo(state.returnTo) ? state.returnTo : undefined;
  const saveLabel = cartSaveLabel(state.cartItemId, mode === "cart" ? "cart" : mode);

  useEffect(() => {
    if (state.tab) setTab(state.tab);
  }, [state.tab]);

  useEffect(() => {
    publishEntryFields({ ...state, tab }, tab);
  }, [state, tab]);

  const sportsbook = state.sportsbook?.trim() || "";
  const league = state.league?.trim() || "";
  const code = state.code?.trim() || "";
  const entityName = (state.entity_name ?? "").trim();
  const structuredAlias =
    league || sportsbook || code || entityName
      ? {
          league,
          sportsbook,
          code,
          entity_name: state.entity_name ?? "",
          entity_type: state.entity_type ?? "team",
          canonical_key: state.canonical_key ?? "",
          alias_kind: state.alias_kind || aliasKindFor(sportsbook),
        }
      : null;

  const entryKey = location.key || "entry";

  const descriptions: Record<Tab, string> = {
    alias: structuredAlias
      ? state.cartItemId
        ? "Update this cart alias. Verify, then Update cart item."
        : mode === "remove"
          ? "Remove this alias pin from Rules. Verify then Add removal to cart or submit alone."
          : "Update this alias pin from Rules. Verify then Add amendment to cart or submit alone."
      : "Paste a crypto id or Optic id. Pick a league when the paste has no prefix. Confirm before it goes to review.",
    league: state.cartItemId
      ? "Update this cart league. Fill Optic league id, Verify, then Update cart item."
      : "Add or update a league row with exchanges. Approve activates live mapping in this environment.",
    market: "Add or replace one market taxonomy / map / ignore rule for an existing league.",
  };

  return (
    <div>
      <PageHeader
        title="Editor"
        description={
          returnTo ? (
            <>
              <Link className="text-brand-700 underline dark:text-brand-300" to={returnTo}>
                ← Back to Proposed
              </Link>
              {" · "}
              {descriptions[tab]}
            </>
          ) : (
            descriptions[tab]
          )
        }
      >
        <EditorModeStatus mode={mode} />
      </PageHeader>
      {mode === "remove" && (state.fromRules || structuredAlias) && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100">
          Removing{" "}
          {structuredAlias
            ? [
                [structuredAlias.sportsbook, structuredAlias.code].filter(Boolean).join(" "),
                "from",
                structuredAlias.entity_name || structuredAlias.canonical_key,
              ]
                .filter(Boolean)
                .join(" ")
            : "this alias"}
          . Live SoT updates only after Proposed approve.
        </div>
      )}
      {mode === "amend" && (state.fromRules || structuredAlias) && (
        <div className="mb-4 notice-amber text-xs">
          Amending{" "}
          {structuredAlias
            ? [
                [structuredAlias.sportsbook, structuredAlias.code].filter(Boolean).join(" "),
                structuredAlias.entity_name || structuredAlias.canonical_key,
              ]
                .filter(Boolean)
                .join(" → ") || "this alias"
            : "an existing mapping"}
          . This stages a change proposal — live SoT updates only after Proposed approve.
        </div>
      )}
      {mode === "amend" && !state.cartItemId && !structuredAlias && !state.fromRules && (
        <div className="mb-4 notice-amber text-xs">
          Pick a mapping from Rules (Propose change) or Coverage / Unmapped Fix, then amend here.
        </div>
      )}
      {mode === "create" && !state.cartItemId && (
        <div className="mb-4 text-xs text-slate-500">
          New mapping — does not change live SoT until Proposed is approved.
        </div>
      )}
      {state.fromRules && mode !== "amend" && (
        <div className="mb-4 notice-brand text-xs">
          {FROM_RULES_BANNER}
        </div>
      )}
      {state.cartItemId ? (
        <div className="mb-4 notice-brand text-xs">
          {FROM_CART_BANNER}
        </div>
      ) : null}
      <TabBar tab={tab} onChange={setTab} />
      {tab === "alias" && (
        <AliasTab
          key={`alias-${entryKey}-${mode}`}
          initialPaste={state.paste ?? ""}
          initialNote={state.note ?? ""}
          structured={structuredAlias}
          removeMode={mode === "remove"}
          cartItemId={state.cartItemId}
          saveLabel={saveLabel}
        />
      )}
      {tab === "league" && (
        <LeagueTab
          key={`league-${entryKey}-${mode}`}
          initialLeague={state.league ?? ""}
          initialNote={state.note ?? ""}
          initialSport={state.sport}
          initialOptic={state.optic_league_id}
          initialFixture={state.fixture_source}
          initialFixtureHorizon={state.fixture_horizon_hours}
          initialExchanges={state.exchanges}
          initialFocusSportsbook={state.focusSportsbook}
          initialEntityType={state.entity_type}
          initialAliasEnforcement={state.alias_enforcement}
          initialRunshopEnabled={state.runshop_enabled}
          cartItemId={state.cartItemId}
          saveLabel={saveLabel}
        />
      )}
      {tab === "market" && (
        <MarketRuleTab
          key={`market-${entryKey}-${mode}`}
          initialLeague={state.league ?? ""}
          initialSportsbook={state.sportsbook ?? ""}
          initialNote={state.note ?? ""}
          initialSourceKey={state.source_key}
          initialAction={state.action}
          initialCanonical={state.canonical_market_type}
          initialSourceKeyType={state.source_key_type}
          initialMatchOperator={state.match_operator}
          initialLineOffset={state.line_offset}
          initialYesSide={state.yes_side}
          initialSideSwap={state.side_swap}
          initialOfficialDescription={state.official_description}
          initialCitationUrl={state.citation_url}
          cartItemId={state.cartItemId}
          saveLabel={saveLabel}
        />
      )}
    </div>
  );
}
