import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Renders agent replies; react-markdown escapes raw HTML by default. */
export function ChatMarkdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
        ul: ({ children }) => <ul className="mb-1 list-disc pl-4 last:mb-0">{children}</ul>,
        ol: ({ children }) => <ol className="mb-1 list-decimal pl-4 last:mb-0">{children}</ol>,
        strong: ({ children }) => (
          <strong className="font-semibold text-slate-900 dark:text-slate-100">{children}</strong>
        ),
        code: ({ children }) => (
          <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] dark:bg-slate-800">
            {children}
          </code>
        ),
        a: ({ href, children }) => (
          <a href={href} target="_blank" rel="noreferrer" className="text-brand-700 underline dark:text-brand-300">
            {children}
          </a>
        ),
        table: ({ children }) => (
          <div className="mb-1 max-w-full overflow-x-auto last:mb-0">
            <table className="w-max min-w-full border-collapse border border-slate-200 text-[11px] dark:border-slate-700">
              {children}
            </table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-slate-50 dark:bg-slate-800">{children}</thead>,
        tbody: ({ children }) => <tbody>{children}</tbody>,
        tr: ({ children }) => (
          <tr className="border-b border-slate-200 last:border-b-0 dark:border-slate-700">{children}</tr>
        ),
        th: ({ children }) => (
          <th className="border border-slate-200 px-1.5 py-1 text-left font-semibold text-slate-900 dark:border-slate-700 dark:text-slate-100">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="border border-slate-200 px-1.5 py-1 align-top dark:border-slate-700">{children}</td>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  );
}
