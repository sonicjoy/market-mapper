import { displayEvidenceRef } from "./evidenceCards";

export type MappingEvidenceView = {
  warnings: string[];
  items: string[];
};

export const AI_UNIQUE_BIND_NOTE =
  "AI suggestion — unique-bind did not apply; human must Approve.";

const OVERLAY_NOTE_TAGS = new Set([
  "crypto player_prop",
  "crypto team_prop",
  "crypto game_prop",
]);

export function normalizeAiNoteRef(ref: string): string {
  let text = ref.trim();
  if (/^ai suggestion/i.test(text)) {
    return AI_UNIQUE_BIND_NOTE;
  }
  for (const tag of OVERLAY_NOTE_TAGS) {
    if (text === tag) return "";
    if (text.endsWith(` ${tag}`)) {
      text = text.slice(0, -(tag.length + 1)).trim();
    }
  }
  return text;
}

function isInternalEvidenceRef(ref: string): boolean {
  const trimmed = ref.trim();
  if (/^rfq_demand:\d+$/i.test(trimmed)) return true;
  return OVERLAY_NOTE_TAGS.has(trimmed.toLowerCase());
}

export function mappingEvidenceView(
  evidence: string[],
  source: string,
  target: string,
): MappingEvidenceView {
  const notes: string[] = [];
  const skips: string[] = [];
  const items: string[] = [];
  for (const ref of evidence) {
    if (isAiSuggestMarker(ref)) continue;
    if (isInternalEvidenceRef(ref)) continue;
    if (isAiNeedleRef(ref)) {
      pushUnique(items, needleLine(ref));
      continue;
    }
    if (isAiNoteRef(ref)) {
      pushUnique(notes, normalizeAiNoteRef(ref));
      continue;
    }
    const skip = skipReasonFromRef(ref);
    if (skip) {
      pushUnique(skips, skipReasonDescription(skip, source, target));
      continue;
    }
    pushUnique(items, displayEvidenceRef(ref));
  }
  return { warnings: [...notes, ...skips], items };
}

export function mappingRowWarnings(
  row: { tier: string; reason: string | null; alternatives: { name: string }[] },
  evidenceWarnings: string[],
): string[] {
  const warnings = [...evidenceWarnings];
  if (row.tier !== "confirmed" && row.reason) {
    pushUnique(warnings, row.reason);
  }
  const runner = row.tier !== "confirmed" ? row.alternatives[0] : undefined;
  if (runner?.name) {
    pushUnique(warnings, `runner-up ${runner.name}`);
  }
  return warnings;
}

export function isAiSuggestMarker(ref: string): boolean {
  const text = ref.trim().toLowerCase();
  return text === "ai:suggest" || text.startsWith("ai:suggest:");
}

export function isAiNoteRef(ref: string): boolean {
  return /^ai suggestion/i.test(ref.trim());
}

export function isAiNeedleRef(ref: string): boolean {
  return /^ai:needle:/i.test(ref.trim());
}

function needleLine(ref: string): string {
  const name = ref.trim().slice("ai:needle:".length).trim();
  return name ? `AI searched for: ${name}` : "";
}

export function skipReasonFromRef(ref: string): string | null {
  const match = /^ai:skip:(.+)$/i.exec(ref.trim());
  const reason = match?.[1]?.trim();
  return reason || null;
}

export function skipReasonDescription(reason: string, source: string, target: string): string {
  const src = source.trim() || "this name";
  const tgt = target.trim() || "this Optic team";
  switch (reason) {
    case "name_ambiguous":
      return `Unsure if ${src} actually is ${tgt}.`;
    case "name_mismatch":
      return `${src} does not match ${tgt} closely enough.`;
    case "collision":
      return `Another Optic owner collides with ${src}; unsure if it is ${tgt}.`;
    case "no_optic_canonical":
      return `No unique Optic market for ${src}; AI guessed ${tgt}.`;
    default:
      return `Unsure if ${src} actually is ${tgt} (${reason.replace(/_/g, " ")}).`;
  }
}

function pushUnique(lines: string[], line: string): void {
  if (!line || lines.includes(line)) return;
  lines.push(line);
}
