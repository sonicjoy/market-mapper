export function readableAliasSourceName(row: {
  kind: string;
  source: {
    name?: string;
    description?: string;
    code?: string;
    id?: string;
    symbol?: string;
    alias_kind?: string;
  };
  target?: { name?: string };
}): string {
  const src = (row.source.name || "").trim();
  const code = (row.source.code || row.source.id || row.source.symbol || "").trim();
  const aliasKind = (row.source.alias_kind || "").trim();
  if (row.kind !== "alias") {
    return src || row.source.description || code || "—";
  }
  if (aliasKind === "name") {
    const pin = code || src;
    if (pin && !isOpaqueId(pin)) return pin;
  }
  if (
    aliasKind === "code" &&
    src &&
    code &&
    src.toLowerCase() !== code.toLowerCase() &&
    /\s/.test(src) &&
    !isOpaqueId(src)
  ) {
    return src;
  }
  if (code && !isOpaqueId(code)) return code;
  if (src && !isOpaqueId(src)) return src;
  return code || src || "—";
}

export function readableAliasSourceSubline(row: {
  kind: string;
  source: {
    platform?: string;
    name?: string;
    description?: string;
    code?: string;
    id?: string;
    symbol?: string;
    slug?: string;
    alias_kind?: string;
    abbr?: string;
  };
}): string {
  const side = row.source;
  const platform = (side.platform || "").trim();
  const pin = (side.code || side.id || side.symbol || "").trim();
  const kind = (side.alias_kind || "").trim();
  const shown = (side.name || "").trim();
  const title = (side.description || "").trim();
  if (row.kind !== "alias") {
    return [platform, pin].filter(Boolean).join(" · ");
  }
  const parts = [platform];
  if (kind === "crypto_id" && pin) {
    parts.push(`crypto_id: ${pin}`);
  } else if (kind === "name" && pin) {
    parts.push(`name: ${pin}`);
  } else if (kind && pin) {
    parts.push(`${kind}: ${pin}`);
  } else if (pin) {
    parts.push(pin);
  }
  if (shown && !sameLabel(shown, pin) && !isOpaqueId(shown)) {
    parts.push(shown);
  }
  const slug = (side.slug || "").trim();
  if (slug) parts.push(`slug: ${slug}`);
  if (title && !sameLabel(title, pin) && !sameLabel(title, shown)) {
    parts.push(title);
  }
  const abbr = (side.abbr || "").trim();
  if (abbr && !sameLabel(abbr, pin) && !sameLabel(abbr, shown)) {
    parts.push(`abbr ${abbr}`);
  }
  return parts.filter(Boolean).join(" · ");
}

export function readableAliasTargetSubline(row: {
  target: {
    platform?: string;
    code?: string;
    id?: string;
    symbol?: string;
    abbr?: string;
  };
}): string {
  const side = row.target;
  const code = (side.code || side.symbol || side.id || "").trim();
  const parts = [side.platform, code].filter(Boolean);
  const abbr = (side.abbr || "").trim();
  if (abbr && !sameLabel(abbr, code)) {
    parts.push(`abbr ${abbr}`);
  }
  return parts.join(" · ");
}

export function isOpticMapping(row: {
  kind: string;
  sportsbook?: string;
  source: { platform?: string };
}): boolean {
  if (row.kind !== "alias") return false;
  const book = (row.sportsbook || "").trim().toLowerCase();
  if (book === "optic") return true;
  return (row.source.platform || "").trim().toLowerCase() === "optic";
}

const OPTIC_IDENTITY_MIDS = new Set(["competitor", "name", "fixture", "abbr", "id"]);

export function opticIdentityEvidence(refs: string[]): string[] {
  return refs.filter((ref) => {
    const parts = ref.split(":");
    const head = (parts[0] || "").toLowerCase();
    const mid = (parts[1] || "").toLowerCase();
    return head === "optic" && OPTIC_IDENTITY_MIDS.has(mid);
  });
}

function sameLabel(left: string, right: string): boolean {
  return Boolean(left) && left.toLowerCase() === right.toLowerCase();
}

function isOpaqueId(value: string): boolean {
  const src = value.trim();
  if (!src) return true;
  if (/\s+vs\.?\s+/i.test(src)) return true;
  if (/\s+@\s+/.test(src)) return true;
  if (/^\d+$/.test(src)) return true;
  if (/^[0-9a-f]{10,}$/i.test(src)) return true;
  return false;
}
