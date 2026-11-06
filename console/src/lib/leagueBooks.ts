import { SPORTSBOOKS, sourceLeagueIdLabel } from "../entryEnums";
import type { LeagueExchange } from "../types";

export type BookChipModel = {
  sportsbook: string;
  present: boolean;
  enabled: boolean;
  source_league_id?: string | null;
};

/** Known books first (missing ones filled in), then any extra exchange pins. */
export function leagueBookSlots(exchanges: LeagueExchange[]): BookChipModel[] {
  const byBook = new Map<string, LeagueExchange>();
  for (const ex of exchanges) {
    const book = (ex.sportsbook || "").trim();
    if (book && !byBook.has(book)) byBook.set(book, ex);
  }
  const out: BookChipModel[] = [];
  for (const book of SPORTSBOOKS) {
    const hit = byBook.get(book);
    if (hit) {
      out.push(fromExchange(hit, true));
      byBook.delete(book);
    } else {
      out.push({ sportsbook: book, present: false, enabled: false });
    }
  }
  for (const leftover of byBook.values()) {
    out.push(fromExchange(leftover, true));
  }
  return out;
}

export const BOOK_CHIP_BASE = "rounded px-1.5 py-0.5 font-mono text-[11px]";

/** Enabled brand chip, disabled strikethrough, absent dashed — Rules leagues + Coverage. */
export function bookChipClass(chip: { present: boolean; enabled: boolean }): string {
  if (!chip.present) {
    return "border border-dashed border-slate-300 text-slate-400 dark:border-slate-600";
  }
  if (!chip.enabled) {
    return "bg-slate-100 text-slate-400 line-through dark:bg-slate-800";
  }
  return "bg-brand-50 text-brand-800 dark:bg-brand-950/60 dark:text-brand-200";
}

export function bookChipTitle(chip: BookChipModel): string {
  if (!chip.present) {
    return "Not on this league. Propose change to add this sportsbook.";
  }
  if (!chip.enabled) {
    if (chip.source_league_id) {
      return `Not enabled for this league (source id: ${chip.source_league_id})`;
    }
    return `Not enabled — missing ${sourceLeagueIdLabel(chip.sportsbook)}. Optic and Polymarket reuse the Optic league id.`;
  }
  return chip.source_league_id ? `source id: ${chip.source_league_id}` : "No source league id";
}

function fromExchange(ex: LeagueExchange, present: boolean): BookChipModel {
  return {
    sportsbook: ex.sportsbook,
    present,
    enabled: ex.enabled !== false,
    source_league_id: ex.source_league_id,
  };
}
