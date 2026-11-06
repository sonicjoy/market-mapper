import { Link } from "react-router-dom";

import { opticDetailLine } from "../lib/coverageTeam";
import type { EntityAliasPin, EntityRuleRow, EntryLocationState } from "../types";

type Props = {
  side: "home" | "away";
  name: string;
  league?: string;
  entity?: EntityRuleRow | null;
  matchEntityType?: string;
  opticId?: string;
  opticAbbr?: string;
};

function aliasEntryState(
  league: string,
  name: string,
  entity?: EntityRuleRow | null,
  pin?: EntityAliasPin,
  matchEntityType?: string,
): EntryLocationState {
  return {
    fromRules: true,
    mode: "amend",
    tab: "alias",
    league,
    entity_name: entity?.entity_name || name,
    canonical_key: entity?.canonical_key,
    entity_type: entity?.entity_type || matchEntityType || "team",
    sportsbook: pin?.sportsbook,
    code: pin?.code,
    alias_kind: pin?.alias_kind,
  };
}

export function CoverageTeamCard({
  side,
  name,
  league,
  entity,
  matchEntityType,
  opticId,
  opticAbbr,
}: Props) {
  const display = entity?.entity_name || name || "—";
  const slug = (league || entity?.league || "").trim();
  const optic = opticDetailLine(opticId, opticAbbr);
  return (
    <div className="rounded border border-slate-200 p-3 dark:border-slate-700">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase text-slate-400">{side}</div>
          <div className="text-sm font-medium">{display}</div>
          {optic ? (
            <div className="font-mono text-[11px] text-slate-400">{optic}</div>
          ) : null}
          {entity ? (
            <div className="font-mono text-[11px] text-slate-400">{entity.canonical_key}</div>
          ) : (
            <div className="text-[11px] text-slate-500">No tip alias</div>
          )}
        </div>
        {slug || name ? (
          <Link
            to="/entry"
            state={aliasEntryState(slug, name, entity, undefined, matchEntityType)}
            className="btn-ghost text-xs"
          >
            Edit
          </Link>
        ) : null}
      </div>
      {entity?.aliases.length ? (
        <table className="mt-2 w-full text-left text-[11px]">
          <thead>
            <tr className="text-slate-400">
              <th className="py-0.5 font-medium">Book</th>
              <th className="py-0.5 font-medium">Kind</th>
              <th className="py-0.5 font-medium">Code</th>
              <th className="py-0.5" />
            </tr>
          </thead>
          <tbody>
            {entity.aliases.map((pin) => (
              <tr
                key={`${pin.sportsbook}:${pin.alias_kind}:${pin.code}`}
                className="border-t border-slate-100 dark:border-slate-800"
              >
                <td className="py-0.5">{pin.sportsbook_label || pin.sportsbook}</td>
                <td className="py-0.5 text-slate-500">{pin.alias_kind}</td>
                <td className="py-0.5 font-mono">{pin.code}</td>
                <td className="py-0.5 text-right">
                  {slug || name ? (
                      <Link
                        to="/entry"
                        state={aliasEntryState(slug, name, entity, pin, matchEntityType)}
                        className="btn-ghost px-1.5 py-0.5 text-[10px]"
                      >
                        Edit
                      </Link>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
