import { Link } from "react-router-dom";

import type { MappingRow, MappingSide } from "../types";
import { formatFixtureStart } from "../lib/coverageList";
import { mappingEvidenceView, mappingRowWarnings } from "../lib/aiSuggestDisplay";
import { leagueDiffSections } from "../lib/leagueDiff";
import {
  readableAliasSourceName,
  readableAliasSourceSubline,
  readableAliasTargetSubline,
  isOpticMapping,
  opticIdentityEvidence,
} from "../lib/mappingDisplay";
import { proposedEditState } from "../lib/proposedEditState";
import { defaultKeep } from "../lib/proposedRail";
import { RuleTextBlock } from "./RuleText";

type Props = {
  row: MappingRow;
  kept: Set<string>;
  onKeep: (key: string) => void;
  onDrop: (key: string) => void;
  returnTo?: string;
};

function actionClass(action: MappingRow["action"]): string {
  switch (action) {
    case "add":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200";
    case "update":
      return "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200";
    case "delete":
      return "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200";
    default: {
      const _exhaustive: never = action;
      return _exhaustive;
    }
  }
}

function tierClass(tier: MappingRow["tier"]): string {
  switch (tier) {
    case "guess":
      return "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200";
    case "ai":
      return "bg-violet-100 text-violet-900 dark:bg-violet-950 dark:text-violet-200";
    case "confirmed":
      return "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300";
    default: {
      const _exhaustive: never = tier;
      return _exhaustive;
    }
  }
}

function Side({
  side,
  heading,
  title,
  subline,
}: {
  side: MappingSide;
  heading: string;
  title: string;
  subline?: string;
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{heading}</div>
      <div className="text-sm font-medium">{title}</div>
      <div className="text-xs text-slate-500 dark:text-slate-400">
        {subline ?? [side.platform, side.code || side.symbol || side.id].filter(Boolean).join(" · ")}
      </div>
    </div>
  );
}

function PinActions({
  row,
  keep,
  onKeep,
  onDrop,
  returnTo,
}: {
  row: MappingRow;
  keep: boolean;
  onKeep: (key: string) => void;
  onDrop: (key: string) => void;
  returnTo?: string;
}) {
  if (row.read_only) {
    return (
      <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        On the tip
      </span>
    );
  }
  return (
    <div className="flex shrink-0 items-center gap-2 md:justify-end">
      <div
        className="inline-flex overflow-hidden rounded-md border border-slate-300 dark:border-slate-600"
        role="group"
        aria-label="Keep or drop this pin"
      >
        <button
          type="button"
          aria-pressed={keep}
          className={`${keep ? "btn-primary" : "btn-ghost"} rounded-none border-0 text-xs`}
          onClick={() => onKeep(row.key)}
        >
          Keep
        </button>
        <button
          type="button"
          aria-pressed={!keep}
          className={`${keep ? "btn-ghost" : "btn-primary"} rounded-none border-0 border-l border-slate-300 text-xs dark:border-slate-600`}
          onClick={() => onDrop(row.key)}
        >
          Drop
        </button>
      </div>
      <Link to="/entry" state={proposedEditState(row, returnTo)} className="btn-ghost text-xs">
        Edit
      </Link>
    </div>
  );
}

function MarketBands({ row }: { row: MappingRow }) {
  if (row.kind !== "market_rule" || !row.venue) return null;
  const bands = [
    ["Venue", row.venue],
    ["Transform", row.transform || ""],
    ["Optic", row.optic || ""],
  ] as const;
  return (
    <div className="mt-2 space-y-1 text-xs text-slate-700 dark:text-slate-200">
      {bands.map(([label, text]) => (
        <div key={label}>
          <span className="mr-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            {label}
          </span>
          {text}
        </div>
      ))}
    </div>
  );
}

function LeagueDelta({ row }: { row: MappingRow }) {
  const sections = leagueDiffSections(row.league_diff);
  const headline = (row.reason || "").trim() || row.target.name || row.league_label;
  return (
    <div className="space-y-2">
      <div className="text-sm font-medium">{headline}</div>
      {sections.map((section) => (
        <div key={section.key}>
          <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            {section.label}
          </div>
          <ul className="mt-0.5 list-disc pl-4 text-sm text-slate-700 dark:text-slate-200">
            {section.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function MappingRowCard({ row, kept, onKeep, onDrop, returnTo }: Props) {
  const keep = defaultKeep(row, kept);
  const extra = row.next_fixtures.slice(1);
  const evidence = isOpticMapping(row) ? opticIdentityEvidence(row.evidence) : row.evidence;
  const sourceName = readableAliasSourceName(row);
  const targetName = row.target.name || row.target.description || row.target.code || "—";
  const view = mappingEvidenceView(evidence, sourceName, targetName);
  const warnings = mappingRowWarnings(row, view.warnings);
  const actions = (
    <PinActions row={row} keep={keep} onKeep={onKeep} onDrop={onDrop} returnTo={returnTo} />
  );
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase dark:bg-slate-800">
          {row.kind.replace("_", " ")}
        </span>
        {row.tier !== "confirmed" ? (
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${tierClass(row.tier)}`}>
            {row.tier}
          </span>
        ) : null}
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${actionClass(row.action)}`}
        >
          {row.action}
        </span>
        {row.league_is_new ? (
          <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
            new league
          </span>
        ) : null}
        {row.kind === "market_rule" && row.clone_from ? (
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            cloned from {row.clone_from}
          </span>
        ) : null}
        {row.rfq_demand ? (
          <span className="text-[10px] text-slate-500">{row.rfq_demand} RFQ</span>
        ) : null}
      </div>
      {row.kind === "league" ? (
        <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-start">
          <LeagueDelta row={row} />
          {actions}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto] md:items-start">
          <Side
            side={row.source}
            heading="Source"
            title={readableAliasSourceName(row)}
            subline={readableAliasSourceSubline(row)}
          />
          <Side
            side={row.target}
            heading="Target"
            title={row.target.name || row.target.description || row.target.code || "—"}
            subline={readableAliasTargetSubline(row)}
          />
          {actions}
        </div>
      )}
      {row.read_only ? (
        <p className="mt-2 text-xs text-slate-500">Already mapped. Not a new tip row.</p>
      ) : null}
      <MarketBands row={row} />
      {row.kind === "market_rule" ? (
        <RuleTextBlock
          official={row.official_description}
          citation={row.citation_url}
          notes={row.notes}
        />
      ) : null}
      <CloneRulesDetails row={row} />
      {row.next_fixtures[0] ? (
        <div className="mt-2 text-xs text-slate-600 dark:text-slate-300">
          Next: {row.next_fixtures[0].label}
          {row.next_fixtures[0].start_date
            ? ` · ${formatFixtureStart(row.next_fixtures[0].start_date)}`
            : ""}
          {extra.length ? (
            <span className="text-slate-400">
              {" "}
              · also pending on {extra.map((fx) => fx.label).join("; ")}
            </span>
          ) : null}
        </div>
      ) : null}
      {warnings.length > 0 ? (
        <div className="mt-2 space-y-1 rounded border border-amber-300/70 bg-amber-50 px-2 py-1.5 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
          {warnings.map((line) => (
            <div key={line}>{line}</div>
          ))}
        </div>
      ) : null}
      {view.items.length > 0 ? (
        <div className="mt-2">
          {row.kind === "league" ? (
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Evidence</div>
          ) : null}
          <ul className="list-disc pl-4 text-[11px] text-slate-500 dark:text-slate-400">
            {view.items.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function CloneRulesDetails({ row }: { row: MappingRow }) {
  if (row.kind !== "league") return null;
  const from = (row.clone_from || "").trim();
  const n = row.cloned_rules?.length ?? 0;
  if (!from) return null;
  const noun = n === 1 ? "market rule" : "market rules";
  return (
    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
      Clones {n} {noun} from {from}. Keep, drop, or edit each market-rule card below.
    </p>
  );
}
