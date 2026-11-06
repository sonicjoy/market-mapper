import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  confirmedPair,
  draftBulkOverride,
  getBulkLegs,
  getOpticMarkets,
  publishBulkOverride,
  searchOpticFixtures,
  selectionKey,
  type DraftResponse,
  type OpticMarket,
} from "../bulkOverrideApi";
import { BulkBatchStatus } from "../components/BulkBatchStatus";
import { BulkPairTable, defaultChoice, pairKey, type PairChoice } from "../components/BulkPairTable";
import { PageHeader } from "../components/PageHeader";
import { formatFixtureStart } from "../lib/coverageList";

/** Yes lands on the win market; a 3-way No lands on double chance when Optic prices it. */
function defaultMarkets(markets: OpticMarket[]): { yes: string; no: string } {
  const ids = markets.map((m) => m.market_id);
  const yes = ids.includes("moneyline") ? "moneyline" : (ids[0] ?? "");
  const threeWay = markets.find((m) => m.market_id === yes)?.selections.some((s) => s.selection === "Draw");
  const no = threeWay && ids.includes("double_chance") ? "double_chance" : yes;
  return { yes, no };
}

function MarketSelect(props: { id: string; label: string; value: string; markets: OpticMarket[]; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="label" htmlFor={props.id}>
        {props.label}
      </label>
      <select id={props.id} className="input w-56" value={props.value} onChange={(e) => props.onChange(e.target.value)}>
        {props.markets.map((m) => (
          <option key={m.market_id} value={m.market_id}>
            {m.market_id} ({m.selections.length})
          </option>
        ))}
      </select>
    </div>
  );
}

export function BulkOverridePage() {
  const [params, setParams] = useSearchParams();
  const event = params.get("event") ?? "";
  const [eventInput, setEventInput] = useState(event);
  const [fixtureQ, setFixtureQ] = useState("");
  const [gameId, setGameId] = useState("");
  const [yesMarket, setYesMarket] = useState("");
  const [noMarket, setNoMarket] = useState("");
  const [draft, setDraft] = useState<DraftResponse | null>(null);
  const [choices, setChoices] = useState<Record<string, PairChoice>>({});
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);

  const legs = useQuery({ queryKey: ["bulk-legs", event], queryFn: () => getBulkLegs(event), enabled: Boolean(event) });
  const day = legs.data?.day ?? "";
  const fixtures = useQuery({
    queryKey: ["bulk-fixtures", fixtureQ, day],
    queryFn: () => searchOpticFixtures(fixtureQ, day),
    enabled: Boolean(legs.data),
  });
  const markets = useQuery({ queryKey: ["bulk-markets", gameId], queryFn: () => getOpticMarkets(gameId), enabled: Boolean(gameId) });
  const marketList = useMemo(() => markets.data?.markets ?? [], [markets.data]);

  useEffect(() => {
    const picked = defaultMarkets(marketList);
    setYesMarket(picked.yes);
    setNoMarket(picked.no);
    setDraft(null);
  }, [marketList]);

  const drafting = useMutation({
    mutationFn: () =>
      draftBulkOverride({
        sportsbook: "kalshi",
        league: legs.data?.league ?? null,
        game_id: gameId,
        market_id: yesMarket,
        no_market_id: noMarket,
        legs: legs.data?.legs ?? [],
      }),
    onSuccess: (out) => {
      setDraft(out);
      setChoices(Object.fromEntries(out.pairs.map((p) => [pairKey(p), defaultChoice(p)])));
      setConfirming(false);
    },
  });

  const selectionsByKey = useMemo(
    () => new Map(marketList.flatMap((m) => m.selections).map((s) => [selectionKey(s), s])),
    [marketList],
  );
  const confirmed = (draft?.pairs ?? []).flatMap((pair) => {
    const choice = choices[pairKey(pair)];
    const target = choice?.include ? selectionsByKey.get(choice.targetKey) : undefined;
    return target ? [confirmedPair(pair, target)] : [];
  });

  const publishing = useMutation({
    mutationFn: () => publishBulkOverride({ sportsbook: "kalshi", reason: reason.trim(), pairs: confirmed }),
  });

  const blocked = legs.data?.block_reason ?? null;
  const yesSelections = marketList.find((m) => m.market_id === yesMarket)?.selections ?? [];
  const noSelections = marketList.find((m) => m.market_id === noMarket)?.selections ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Bulk override"
        description="Map every unmapped selection of one Kalshi event to Optic in one batch. Each row is a mapping_override: it binds one venue selection in one fixture and does not carry to the next fixture - fix the rule too."
      />
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setParams(eventInput.trim() ? { event: eventInput.trim().toUpperCase() } : {});
          setGameId("");
          setDraft(null);
        }}
      >
        <div className="min-w-[20rem] flex-1">
          <label className="label" htmlFor="bulk-event">
            Kalshi event ticker
          </label>
          <input
            id="bulk-event"
            className="input w-full font-mono"
            placeholder="KXNHLGAME-26SEP26ANALA"
            value={eventInput}
            onChange={(e) => setEventInput(e.target.value)}
          />
        </div>
        <button type="submit" className="btn-primary">
          Load legs
        </button>
      </form>
      {blocked ? <p className="notice-amber text-xs">{blocked}</p> : null}
      {legs.isError ? <p className="notice-red text-xs">{legs.error.message}</p> : null}
      {legs.data ? (
        <p className="text-xs text-slate-600 dark:text-slate-300">
          {legs.data.legs.length} unmapped selection(s) in the last 48h
          {legs.data.league ? ` · tip league ${legs.data.league}` : " · league not on the tip"}
          {day ? ` · ${day}` : ""}.
          {legs.data.legs.length === 0 ? " Nothing to override: every leg already has a market_mapping row." : ""}
        </p>
      ) : null}

      {legs.data && legs.data.legs.length ? (
        <section className="card space-y-2">
          <h2 className="text-sm font-semibold">1. Optic fixture</h2>
          <input
            className="input w-full"
            placeholder={`Team name (fixtures on ${day || "any day"} in the rank window)`}
            value={fixtureQ}
            onChange={(e) => setFixtureQ(e.target.value)}
          />
          <ul className="max-h-48 space-y-1 overflow-auto text-xs">
            {(fixtures.data?.fixtures ?? []).map((fx) => (
              <li key={fx.game_id}>
                <label className="flex cursor-pointer items-center gap-2">
                  <input type="radio" name="bulk-fixture" checked={gameId === fx.game_id} onChange={() => setGameId(fx.game_id)} />
                  <span>
                    {fx.away} @ {fx.home}
                  </span>
                  <span className="text-slate-500">
                    {formatFixtureStart(fx.start_date)} · {fx.league} · <span className="font-mono">{fx.game_id}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {gameId && marketList.length ? (
        <section className="card space-y-2">
          <h2 className="text-sm font-semibold">2. Optic markets</h2>
          <div className="flex flex-wrap items-end gap-2">
            <MarketSelect id="bulk-yes" label="Yes sides map to" value={yesMarket} markets={marketList} onChange={setYesMarket} />
            <MarketSelect id="bulk-no" label="No sides map to" value={noMarket} markets={marketList} onChange={setNoMarket} />
            <button type="button" className="btn-primary" disabled={drafting.isPending} onClick={() => drafting.mutate()}>
              {drafting.isPending ? "Drafting…" : "Draft pairs"}
            </button>
          </div>
          {drafting.isError ? <p className="notice-red text-xs">{drafting.error.message}</p> : null}
        </section>
      ) : null}

      {draft ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">
            3. Confirm pairs{" "}
            <span className="font-normal text-slate-500">
              {draft.counts.confident} confident · {draft.counts.review} review · {draft.counts.ambiguous} ambiguous ·{" "}
              {draft.counts.no_match} no match
            </span>
          </h2>
          <BulkPairTable
            pairs={draft.pairs}
            legs={legs.data?.legs ?? []}
            yesMarket={yesSelections}
            noMarket={noSelections}
            choices={choices}
            onChange={(key, next) => {
              setChoices((prev) => ({ ...prev, [key]: next }));
              setConfirming(false);
            }}
          />
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[20rem] flex-1">
              <label className="label" htmlFor="bulk-reason">
                Reason (stored on every override)
              </label>
              <input id="bulk-reason" className="input w-full" value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
            {confirming ? (
              <button
                type="button"
                className="btn-primary"
                disabled={publishing.isPending}
                onClick={() => publishing.mutate()}
              >
                {publishing.isPending ? "Publishing…" : `Confirm: publish ${confirmed.length} override(s)`}
              </button>
            ) : (
              <button
                type="button"
                className="btn-primary"
                disabled={Boolean(blocked) || !confirmed.length || !reason.trim() || Boolean(publishing.data)}
                onClick={() => setConfirming(true)}
              >
                Publish {confirmed.length} override(s)…
              </button>
            )}
          </div>
          {publishing.isError ? <p className="notice-red text-xs">{publishing.error.message}</p> : null}
          {publishing.data ? <BulkBatchStatus batchId={publishing.data.batch_id} /> : null}
        </section>
      ) : null}
    </div>
  );
}
