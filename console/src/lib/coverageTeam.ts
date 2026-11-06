export function opticDetailLine(id?: string, abbr?: string): string | null {
  const oid = (id || "").trim();
  const ab = (abbr || "").trim();
  if (!oid && !ab) return null;
  const label = ab || "(empty abbr)";
  return oid ? `Optic ${label} · id ${oid}` : `Optic ${label}`;
}
