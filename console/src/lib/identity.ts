// The browser tab has to say which estate it is showing. Every WSD console shares one tab strip, and
// reading a test mapping proposal as a live one is the mistake worth spending a suffix on.
//
// The env comes from the API's `meta.env` (inferred from GCP_PROJECT), not a build arg: one image is
// deployed per overlay, so anything baked at build time is wrong in whichever deploy it doesn't match.

/** `test` → "Test", `prod` → "Prod". Empty off-deploy, where no claim beats a wrong one. */
export function envLabel(env?: string): string {
  const e = (env ?? "").trim().toLowerCase();
  if (!e) return "";
  if (e === "local") return "Local";
  return e.charAt(0).toUpperCase() + e.slice(1);
}

/** Estate tab convention: `MM <console> (<Env>)`. */
export function consoleTitle(env?: string): string {
  const e = envLabel(env);
  return e ? `MM Mappings (${e})` : "MM Mappings";
}
