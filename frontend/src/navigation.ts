export function safeReturnTo(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/tenders") || /[\\\u0000-\u001f]/.test(raw) || raw.length > 4096) return "/tenders";
  try {
    decodeURI(raw);
    const url = new URL(raw, "https://internal.invalid");
    if (url.origin !== "https://internal.invalid" || url.pathname !== "/tenders" || url.hash) return "/tenders";
    return url.pathname + url.search;
  } catch { return "/tenders"; }
}
export function tenderDestination(id: string, returnTo?: string | null): string {
  const query = new URLSearchParams({ returnTo: safeReturnTo(returnTo) });
  return `/tenders/${encodeURIComponent(id)}?${query}`;
}
export function researchDestination(path: string, id: string, returnTo?: string | null): string {
  return `${path}?${new URLSearchParams({ tender: id, returnTo: safeReturnTo(returnTo) })}`;
}
export function savedViewDestination(payload: unknown): { url: string | null; unsupported: string[]; invalid: boolean } {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return { url: null, unsupported: [], invalid: true };
  const allowed = new Set(["q", "level", "procedure", "min", "min_risk", "offset"]);
  const row = payload as Record<string, unknown>;
  const unsupported = Object.keys(row).filter((key) => !allowed.has(key));
  const params = new URLSearchParams();
  let invalid = false;
  for (const [key, value] of Object.entries(row)) {
    if (!allowed.has(key) || value === "" || value === null) continue;
    if (["q", "level", "procedure"].includes(key)) {
      if (typeof value !== "string" || key === "level" && !["", "unscored", "low", "medium", "high", "critical"].includes(value)) invalid = true;
      else params.set(key, value);
    } else {
      if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || key !== "offset" && (value > 95 || value % 5 !== 0) || key === "offset" && (!Number.isSafeInteger(value) || value % 40 !== 0)) invalid = true;
      else params.set(key === "min_risk" ? "min" : key, String(value));
    }
  }
  if (row.min !== undefined && row.min_risk !== undefined && row.min !== row.min_risk) invalid = true;
  return { url: unsupported.length || invalid ? null : `/tenders${params.size ? `?${params}` : ""}`, unsupported, invalid };
}
