/** Page indices and ellipsis for numeric pager controls (0-based pages). */

export function pagerPageItems(page: number, lastPage: number): Array<number | "ellipsis"> {
  if (lastPage < 0) return [];
  const totalPages = lastPage + 1;
  if (totalPages <= 1) return [0];
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i);
  }

  const pages = new Set<number>([0, lastPage, page]);
  if (page > 0) pages.add(page - 1);
  if (page < lastPage) pages.add(page + 1);

  const sorted = [...pages].sort((a, b) => a - b);
  const out: Array<number | "ellipsis"> = [];
  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) {
      out.push("ellipsis");
    }
    out.push(sorted[i]);
  }
  return out;
}
