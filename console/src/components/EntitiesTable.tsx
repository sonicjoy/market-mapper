import type { EntityAliasPin, EntityRuleRow } from "../types";
import { RulesPager } from "./RulesPager";
import { SortTh } from "./SortTh";
import type { PageSize, SortDir } from "../lib/rulesQuery";

type Props = {
  rows: EntityRuleRow[];
  count: number;
  page: number;
  pageSize: number;
  sort: string;
  dir: SortDir;
  onSort: (column: string) => void;
  onPropose: (row: EntityRuleRow, pin: EntityAliasPin) => void;
  onRemove: (row: EntityRuleRow, pin: EntityAliasPin) => void;
  onPage: (p: number) => void;
  onPageSize: (size: PageSize) => void;
};

function ProposeBtn({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="btn-ghost text-xs" onClick={onClick}>
      Propose change
    </button>
  );
}

function RemoveBtn({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="btn-ghost text-xs text-red-700 dark:text-red-300" onClick={onClick}>
      Remove
    </button>
  );
}

export function EntitiesTable({
  rows,
  count,
  page,
  pageSize,
  sort,
  dir,
  onSort,
  onPropose,
  onRemove,
  onPage,
  onPageSize,
}: Props) {
  return (
    <div className="panel">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          <tr>
            <SortTh column="league" label="League" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="entity" label="Entity" sort={sort} dir={dir} onSort={onSort} />
            <SortTh column="sportsbook" label="Sportsbook" sort={sort} dir={dir} onSort={onSort} />
            <th className="px-3 py-2">Kind</th>
            <SortTh column="code" label="Code" sort={sort} dir={dir} onSort={onSort} />
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <EntityGroup
              key={`${row.league}:${row.canonical_key}`}
              row={row}
              onPropose={onPropose}
              onRemove={onRemove}
            />
          ))}
        </tbody>
      </table>
      {count === 0 && <p className="px-3 py-4 text-sm text-slate-500 dark:text-slate-400">No matches.</p>}
      <RulesPager
        count={count}
        page={page}
        pageSize={pageSize}
        onPage={onPage}
        onPageSize={onPageSize}
      />
    </div>
  );
}

function EntityGroup({
  row,
  onPropose,
  onRemove,
}: {
  row: EntityRuleRow;
  onPropose: (row: EntityRuleRow, pin: EntityAliasPin) => void;
  onRemove: (row: EntityRuleRow, pin: EntityAliasPin) => void;
}) {
  const pins = row.aliases.length ? row.aliases : [null];
  const span = pins.length;
  return (
    <>
      {pins.map((pin, i) => (
        <tr key={`${row.canonical_key}-${pin?.sportsbook ?? i}-${pin?.code ?? i}`} className="border-t border-slate-100 dark:border-slate-800">
          {i === 0 ? (
            <>
              <td className="px-3 py-2 align-top" rowSpan={span}>
                {row.league_label}
              </td>
              <td className="px-3 py-2 align-top" rowSpan={span}>
                <div>{row.entity_name}</div>
                <div className="font-mono text-[11px] text-slate-400">{row.canonical_key}</div>
              </td>
            </>
          ) : null}
          <td className="px-3 py-2">{pin?.sportsbook_label || pin?.sportsbook || "—"}</td>
          <td className="px-3 py-2 text-xs text-slate-500">{pin?.alias_kind || "—"}</td>
          <td className="px-3 py-2 font-mono">{pin?.code || "—"}</td>
          <td className="px-3 py-2 text-right">
            {pin ? (
              <span className="inline-flex items-center justify-end gap-2">
                <ProposeBtn onClick={() => onPropose(row, pin)} />
                <RemoveBtn onClick={() => onRemove(row, pin)} />
              </span>
            ) : null}
          </td>
        </tr>
      ))}
    </>
  );
}
