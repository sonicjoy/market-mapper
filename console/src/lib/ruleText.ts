/** Official description and citation display. */

/** Proposal cards say this when the drafter had no venue text and no citation. */
export const OFFICIAL_ABSENT = "No official description or citation URL.";

export function textOrDash(value: string | null | undefined): string {
  const text = (value ?? "").trim();
  return text || "—";
}

/** Rules table keeps a dash for null. Proposal cards say the text is missing. */
export function officialCellText(value: string | null | undefined): string {
  const text = (value ?? "").trim();
  return text || OFFICIAL_ABSENT;
}

/** http(s) only. Anything else is shown as text, not a link. */
export function httpCitation(value: string | null | undefined): string | null {
  const text = (value ?? "").trim();
  if (!/^https?:\/\//i.test(text)) return null;
  return text;
}
