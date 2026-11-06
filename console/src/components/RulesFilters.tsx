import { ALIAS_SPORTSBOOKS, CANONICAL_MARKET_TYPES, MARKET_ACTIONS, SPORTSBOOKS } from "../entryEnums";
import { CANONICAL_NONE, type RulesKind } from "../lib/rulesQuery";
import { MultiSelect } from "./MultiSelect";

type FilterPatch = {
  league?: string[];
  sportsbook?: string[];
  canonical?: string[];
  action?: string[];
  page?: number;
};

const CANONICAL_OPTIONS = [
  { value: CANONICAL_NONE, label: "(none)" },
  ...CANONICAL_MARKET_TYPES.map((value) => ({ value, label: value })),
];

/** Multi-select filters for the Rules explorer; unused fields stay in the URL. */
export function RulesFilters({
  kind,
  league,
  sportsbook,
  canonical,
  action,
  leagueOptions,
  onChange,
}: {
  kind: RulesKind;
  league: string[];
  sportsbook: string[];
  canonical: string[];
  action: string[];
  leagueOptions: { value: string; label: string }[];
  onChange: (patch: FilterPatch) => void;
}) {
  const hasFilters = Boolean(league.length || sportsbook.length || canonical.length || action.length);
  return (
    <div className="flex min-w-0 flex-[2_1_28rem] flex-wrap items-center gap-2">
      <MultiSelect
        id="rules-league"
        label="League"
        values={league}
        options={leagueOptions}
        onChange={(next) => onChange({ league: next, page: 0 })}
      />
      <MultiSelect
        id="rules-sportsbook"
        label="Sportsbook"
        values={sportsbook}
        options={kind === "entities" ? ALIAS_SPORTSBOOKS : SPORTSBOOKS}
        onChange={(next) => onChange({ sportsbook: next, page: 0 })}
      />
      {kind === "market_rules" ? (
        <>
          <MultiSelect
            id="rules-canonical"
            label="Canonical"
            values={canonical}
            options={CANONICAL_OPTIONS}
            onChange={(next) => onChange({ canonical: next, page: 0 })}
          />
          <MultiSelect
            id="rules-action"
            label="Action"
            values={action}
            options={MARKET_ACTIONS}
            onChange={(next) => onChange({ action: next, page: 0 })}
          />
        </>
      ) : null}
      {hasFilters ? (
        <button
          type="button"
          className="btn-ghost text-xs"
          onClick={() =>
            onChange({ league: [], sportsbook: [], canonical: [], action: [], page: 0 })
          }
        >
          Clear filters
        </button>
      ) : null}
    </div>
  );
}
