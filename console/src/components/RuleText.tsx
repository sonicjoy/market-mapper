import { httpCitation, officialCellText, textOrDash } from "../lib/ruleText";

type RuleText = {
  official?: string | null;
  citation?: string | null;
  notes?: string | null;
};

export function CitationLink({ url }: { url?: string | null }) {
  const href = httpCitation(url);
  if (!href) return <>{textOrDash(url)}</>;
  return (
    <a className="break-all underline" href={href} rel="noreferrer" target="_blank">
      {href}
    </a>
  );
}

export function RuleTextCells({ official, citation, notes }: RuleText) {
  return (
    <>
      <td className="max-w-xs whitespace-normal px-3 py-2">{textOrDash(official)}</td>
      <td className="max-w-xs whitespace-normal px-3 py-2">
        <CitationLink url={citation} />
      </td>
      <td className="max-w-xs whitespace-normal px-3 py-2">{textOrDash(notes)}</td>
    </>
  );
}

export function RuleTextBlock({ official, citation, notes }: RuleText) {
  return (
    <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
      <div>
        <dt className="font-semibold uppercase tracking-wide text-slate-400">Official description</dt>
        <dd className="text-slate-700 dark:text-slate-200">{officialCellText(official)}</dd>
      </div>
      <div>
        <dt className="font-semibold uppercase tracking-wide text-slate-400">Citation</dt>
        <dd className="text-slate-700 dark:text-slate-200">
          <CitationLink url={citation} />
        </dd>
      </div>
      <div>
        <dt className="font-semibold uppercase tracking-wide text-slate-400">Notes</dt>
        <dd className="text-slate-700 dark:text-slate-200">{textOrDash(notes)}</dd>
      </div>
    </dl>
  );
}
