import type { BulkLeg, DraftPair, OpticSelection, PairStatus } from "../bulkOverrideApi";
import { selectionKey, selectionLabel } from "../bulkOverrideApi";

export type PairChoice = { include: boolean; targetKey: string };

const STATUS_CHIP: Record<PairStatus, { label: string; className: string }> = {
  confident: { label: "Confident", className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200" },
  review: { label: "Review", className: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200" },
  ambiguous: { label: "Ambiguous", className: "bg-orange-100 text-orange-900 dark:bg-orange-950 dark:text-orange-200" },
  no_match: { label: "No match", className: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200" },
};

/** Pair key: one venue selection. */
export function pairKey(pair: Pick<DraftPair, "source_market_id" | "source_selection_id">): string {
  return `${pair.source_market_id}|${pair.source_selection_id}`;
}

/** Default choice: only confident pairs are pre-ticked; everything else needs a human. */
export function defaultChoice(pair: DraftPair): PairChoice {
  return { include: pair.status === "confident" && pair.target !== null, targetKey: pair.target ? selectionKey(pair.target) : "" };
}

/** Options for one row: the drafted target, its alternatives, then the rest of the market. */
export function rowOptions(pair: DraftPair, market: OpticSelection[]): OpticSelection[] {
  const seen = new Set<string>();
  const out: OpticSelection[] = [];
  for (const sel of [...(pair.target ? [pair.target] : []), ...pair.alternatives, ...market]) {
    const key = selectionKey(sel);
    if (!seen.has(key)) {
      seen.add(key);
      out.push(sel);
    }
  }
  return out;
}

type Props = {
  pairs: DraftPair[];
  legs: BulkLeg[];
  yesMarket: OpticSelection[];
  noMarket: OpticSelection[];
  choices: Record<string, PairChoice>;
  onChange: (key: string, next: PairChoice) => void;
};

export function BulkPairTable({ pairs, legs, yesMarket, noMarket, choices, onChange }: Props) {
  const demand = new Map(legs.map((leg) => [pairKey(leg), leg.demand]));
  return (
    <div className="card overflow-x-auto p-0">
      <table className="w-full min-w-[48rem] text-left text-xs">
        <thead className="border-b border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-300">
          <tr>
            <th className="w-10 px-3 py-2" />
            <th className="px-3 py-2">Venue selection</th>
            <th className="px-3 py-2 text-right">Failed RFQs 48h</th>
            <th className="px-3 py-2">Draft</th>
            <th className="px-3 py-2">Optic selection</th>
          </tr>
        </thead>
        <tbody>
          {pairs.map((pair) => {
            const key = pairKey(pair);
            const choice = choices[key] ?? defaultChoice(pair);
            const options = rowOptions(pair, pair.source_selection_id.toLowerCase() === "no" ? noMarket : yesMarket);
            const chip = STATUS_CHIP[pair.status];
            return (
              <tr key={key} className="border-b border-slate-100 align-top dark:border-slate-800">
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={`Include ${pair.source_market_id} ${pair.source_selection_id}`}
                    className="h-4 w-4 accent-brand-600"
                    checked={choice.include}
                    disabled={!choice.targetKey}
                    onChange={(e) => onChange(key, { ...choice, include: e.target.checked })}
                  />
                </td>
                <td className="px-3 py-2">
                  <span className="font-mono text-[11px]">{pair.source_market_id}</span>{" "}
                  <span className="font-semibold uppercase">{pair.source_selection_id}</span>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{(demand.get(key) ?? 0).toLocaleString()}</td>
                <td className="px-3 py-2">
                  <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${chip.className}`}>{chip.label}</span>
                  <p className="mt-1 text-[11px] text-slate-500">{pair.reason}</p>
                </td>
                <td className="px-3 py-2">
                  <select
                    className="input w-full text-xs"
                    aria-label={`Optic selection for ${pair.source_market_id} ${pair.source_selection_id}`}
                    value={choice.targetKey}
                    onChange={(e) =>
                      onChange(key, { include: e.target.value !== "" && choice.include, targetKey: e.target.value })
                    }
                  >
                    <option value="">(do not override)</option>
                    {options.map((sel) => (
                      <option key={selectionKey(sel)} value={selectionKey(sel)}>
                        {sel.market_id}: {selectionLabel(sel)}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
