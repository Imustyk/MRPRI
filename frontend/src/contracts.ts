import i18n from "./i18n";

export const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
export const percentile = (v: unknown) => finite(v) && v >= 0 && v <= 100;
export const votes = (v: unknown) => finite(v) && Number.isInteger(v) && v >= 0 && v <= 4;
export const count = (v: unknown) => finite(v) && v >= 0;
const bands = new Set(["unscored", "low", "medium", "high", "critical"]);
const ranked = new Set(["risk_score", "score_percentile", "percentile", "max_risk", "avg_risk", "mean_risk"]);
const raw = new Set(["iso_score", "lof_score", "svm_score", "rule_score"]);
const shares = new Set(["share", "missing_rate", "iqr_outlier_rate", "corpus_rate", "single_bidder_share", "agreement"]);

export class ApiContractError extends Error {
  constructor(public field: string, public rule: string) {
    super(i18n.t("completion.contract_error", { field, rule: i18n.t(`completion.rules.${rule}`) }));
    this.name = "ApiContractError";
  }
}
export class ApiHttpError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = "ApiHttpError"; }
}
function requireRule(ok: boolean, field: string, rule: string) {
  if (!ok) throw new ApiContractError(field, rule);
}
export function assertApiData(url: string, payload: unknown): void {
  const path = url.split("?")[0];
  requireRule(payload !== null && typeof payload === "object" && !Array.isArray(payload), path, "object");
  function walk(value: unknown, at: string): void {
    if (!value || typeof value !== "object") return;
    if (Array.isArray(value)) { value.forEach((item, index) => walk(item, `${at}[${index}]`)); return; }
    const row = value as Record<string, unknown>;
    if (["/api/meta.unavailable", "/api/meta.risk_bands"].includes(at) && Object.values(row).every(item => typeof item === "string")) return;
    const baselineMap = /^\/api\/evaluation\.external_labels\[\d+\]\.baselines$/.test(at);
    for (const [key, item] of Object.entries(row)) {
      const field = `${at}.${key}`;
      if (typeof item === "number") requireRule(finite(item), field, "raw_score");
      if (item !== null && item !== undefined) {
        if (ranked.has(key)) requireRule(percentile(item), field, "percentile");
        if (key === "n_models_flagging") requireRule(votes(item), field, "votes");
        else if (!baselineMap && !at.includes(".params") && (/^n(?:_|$)/.test(key) || ["total", "weight", "records", "scored", "unscored", "zeros", "negative", "sampled", "bytes", "min_pairs", "dropped", "degree", "awards", "pairs_all"].includes(key) || /(_count|_shown|_qualifying)$/.test(key))) requireRule(count(item), field, "count");
        if (raw.has(key)) requireRule(finite(item) && (!(key === "rule_score" || key === "lof_score") || item >= 0), field, "raw_score");
        const agreementRecord = key === "agreement" && at === "/api/explainability.xai_consistency";
        if (agreementRecord) requireRule(typeof item === "object" && !Array.isArray(item), field, "object");
        else if (shares.has(key) && !(key === "agreement" && Array.isArray(item))) requireRule(finite(item) && item >= 0 && item <= 1, field, "share");
        if (key === "risk_level" || key === "band" && at.endsWith(".consensus")) requireRule(typeof item === "string" && bands.has(item), field, "band");
        if (key === "consensus_flag" || key === "flag" && at.endsWith(".consensus")) requireRule(typeof item === "boolean", field, "boolean");
        if (key === "model_flags") {
          requireRule(typeof item === "object" && !Array.isArray(item), field, "object");
          for (const [model, verdict] of Object.entries(item as object)) requireRule(verdict === null || typeof verdict === "boolean", `${field}.${model}`, "boolean");
        }
        if (key === "level_counts" || key === "procedure_counts" || key === "counts") {
          requireRule(typeof item === "object" && !Array.isArray(item), field, "object");
          for (const [name, n] of Object.entries(item as object)) requireRule(count(n), `${field}.${name}`, "count");
        }
      }
      walk(item, field);
    }
    const rankedField = typeof row.column === "string" && ranked.has(row.column) || typeof row.key === "string" && ranked.has(row.key);
    const rankedValue = typeof row.value === "string" && ranked.has(row.value);
    const checkSummary = (summary: unknown, label: string) => { if (summary && typeof summary === "object") for (const [key, n] of Object.entries(summary)) if (["min","max","mean","median","p25","p75","p90","p99"].includes(key) && n !== null) requireRule(percentile(n), `${label}.${key}`, "percentile"); };
    if (rankedField) {
      checkSummary(row.summary, `${at}.summary`);
    }
    if (rankedValue && Array.isArray(row.groups)) row.groups.forEach((group, i) => checkSummary(group, `${at}.groups[${i}]`));
    if (Array.isArray(row.points)) for (const point of row.points) for (const axis of ["x", "y"]) if (typeof row[axis] === "string" && ranked.has(row[axis] as string)) requireRule(percentile(point[axis]), `${at}.points.${axis}`, "percentile");
    if (rankedValue && Array.isArray(row.matrix)) for (const line of row.matrix) for (const n of line) if (n != null) requireRule(percentile(n), `${at}.matrix`, "percentile");
    if (typeof row.field === "string" && ranked.has(row.field) && row.value != null) requireRule(percentile(row.value), `${at}.value`, "percentile");
    if (typeof row.field === "string" && raw.has(row.field) && row.score != null) requireRule(finite(row.score) && (!["rule_score", "lof_score"].includes(row.field) || row.score >= 0), `${at}.score`, "raw_score");
  }
  walk(payload, path);
  const body = payload as Record<string, unknown>;
  const arrays: Record<string, string[]> = {
    "/api/tenders": ["items"], "/api/graph": ["nodes", "links"],
    "/api/analytics/features": ["features", "categories"], "/api/analytics/correlations": ["columns", "matrix", "pairs"],
    "/api/analytics/distribution": ["bins", "ecdf", "groups"], "/api/analytics/scatter": ["points"],
    "/api/analytics/group-compare": ["groups"], "/api/analytics/crosstab": ["rows", "cols", "matrix"],
  };
  if (path === "/api/stats") requireRule(body.procedure_counts != null && typeof body.procedure_counts === "object" && !Array.isArray(body.procedure_counts), `${path}.procedure_counts`, "object");
  if (/^\/api\/workspace\/(cases|annotations|watchlists|views|activity)$/.test(path) && url && "items" in body) requireRule(Array.isArray(body.items), `${path}.items`, "array");
  for (const name of arrays[path] ?? []) requireRule(Array.isArray(body[name]), `${path}.${name}`, "array");
  if (path.endsWith("/model-analysis")) {
    requireRule(Array.isArray(body.detectors) && Array.isArray(body.agreement), path, "array");
    for (const model of body.detectors as Record<string, unknown>[]) {
      requireRule(model != null && typeof model === "object", path, "object");
      requireRule(["statistical_mad_zscore", "isolation_forest", "local_outlier_factor", "one_class_svm"].includes(String(model.key)), `${path}.key`, "raw_score");
      requireRule(["flagged", "not_flagged", "unavailable"].includes(String(model.verdict)), `${path}.verdict`, "boolean");
      requireRule(model.score === null || finite(model.score) && (!["statistical_mad_zscore", "local_outlier_factor"].includes(String(model.key)) || model.score >= 0), `${path}.score`, "raw_score");
      requireRule(Array.isArray(model.features) && model.params !== null && typeof model.params === "object", path, "object");
      if (model.threshold != null) requireRule(finite((model.threshold as {value: unknown}).value), `${path}.threshold`, "raw_score");
      requireRule(Array.isArray(model.bins), `${path}.bins`, "array");
      const bins = model.bins as Record<string, unknown>[];
      for (const bin of bins) requireRule(finite(bin.start) && finite(bin.end) && bin.start <= bin.end && Number.isInteger(bin.index) && count(bin.index), `${path}.bins`, "bins");
      const unproven = !(typeof body.run_id === "string" && body.run_id.trim());
      requireRule(!unproven || (!bins.length && model.threshold == null && model.score_percentile == null && model.n_reference === 0), `${path}.run_id`, "provenance");
    }
    if (!body.run_id) { requireRule(body.n_reference === 0, `${path}.n_reference`, "provenance"); }
    if (!body.run_id) requireRule((body.agreement as unknown[][]).flat().every((cell) => (cell as { agreement?: unknown }).agreement == null), `${path}.agreement`, "provenance");
  }
}
