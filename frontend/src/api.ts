/**
 * "unscored" is not a risk level: it means no detector ever produced output for
 * that record. It is kept as its own band so the UI never implies that ~151k
 * procedures were examined and cleared.
 */
export type RiskLevel = "unscored" | "low" | "medium" | "high" | "critical";

export const RISK_ORDER: RiskLevel[] = [
  "unscored",
  "low",
  "medium",
  "high",
  "critical",
];

export const RISK_COLOR: Record<RiskLevel, string> = {
  unscored: "#8a93a0",
  low: "#2a6b4a",
  medium: "#c98a12",
  high: "#d1601a",
  critical: "#b4232c",
};

export type Tender = {
  tender_id: string;
  ocid: string;
  title: string | null;
  buyer_id: string | null;
  buyer_name: string | null;
  buyer_identifier: string | null;
  buyer_locality: string | null;
  /** MTender publishes CPV codes only, so the label is always null. */
  cpv_code: string | null;
  cpv_label: null;
  procedure: string | null;
  procurement_method: string | null;
  status: string | null;
  published_at: string | null;
  list_date: string | null;
  tender_start: string | null;
  bid_deadline: string | null;
  award_date: string | null;
  bid_window_days: number | null;
  estimated_value_mdl: number | null;
  /** First award only. Multi-lot tenders are understated by this figure. */
  award_value_mdl: number | null;
  /** Sum over every awarded lot: the only figure comparable with the estimate. */
  award_total_mdl: number | null;
  currency: string;
  winner_name: string | null;
  winner_idno: string | null;
  winner_id: string | null;
  /** Distinct bidders: the only sound competition measure. */
  n_bidders: number | null;
  /** Lot-level bid records (bids.details is per lot, not per bidder). */
  n_bids: number | null;
  n_bid_records: number | null;
  n_lots: number | null;
  n_awards: number | null;
  /**
   * Percentile rank of the record's most extreme model, 0-100. It is a rank
   * within this dataset, not a probability, and not comparable across runs.
   */
  risk_score: number | null;
  risk_level: RiskLevel;
  n_models_flagging: number | null;
  iso_score: number | null;
  lof_score: number | null;
  svm_score: number | null;
  rule_score: number | null;
  flags: string[];
  single_bidder: number | null;
  short_deadline: number | null;
  value_vs_cpv_median: number | null;
  winner_share_of_buyer_awards: number | null;
  buyer_supplier_repeat_share: number | null;
  estimate_to_award_ratio: number | null;
  has_bid_data: boolean | null;
  has_award_data: boolean | null;
  /** Not published for most procurements. */
  bids: null;
  /** Ground-truth labels exist only for the synthetic dataset. */
  planted_pattern: null;
  is_planted_anomaly: null;
};

export type Stats = {
  n_tenders: number;
  n_buyers: number;
  n_winners: number;
  total_award_mdl: number;
  high_risk_count: number;
  high_risk_value_mdl: number;
  single_bidder_share: number | null;
  mean_n_bidders: number | null;
  mean_n_bid_records: number | null;
  n_with_bid_data: number;
  mean_risk: number | null;
  level_counts: Record<string, number>;
  procedure_counts: Record<string, number>;
  top_cpv: { cpv_code: string; cpv_label: null; n: number; avg_risk: number | null; value: number }[];
  monthly: { month: string; n: number; avg_risk: number; value: number }[];
  top_risky_buyers: {
    buyer_id: string;
    buyer_name: string;
    n: number;
    avg_risk: number | null;
    high: number;
  }[];
  metrics: { available: boolean; reason?: string };
  features: string[];
};

export type Meta = {
  source: string;
  n_tenders: number;
  scored: number;
  feature_columns: string[];
  indicator_columns: string[];
  /** Fields MTender does not publish, with the reason for each. */
  unavailable: Record<string, string>;
  risk_bands: Record<string, string>;
  model: string;
  etl_run_id?: string;
};

export type Indicators = Record<string, { n: number } & Record<string, number | null>>;

export type Health = {
  ok: boolean;
  artefacts: boolean;
  source: string;
  model_present: boolean;
  mongodb: MongoStatus;
};

export type MongoStatus = {
  connected: boolean;
  error?: string;
  uri?: string;
  set_name?: string | null;
  is_writable_primary?: boolean;
  hosts?: string[];
  my_state?: number;
  members?: { name: string; state: string }[];
  database?: string;
  transactions?: boolean;
  collections?: Record<string, number>;
};

export type GraphData = {
  nodes: { id: string; kind: string; name: string; locality: string; degree: number }[];
  links: {
    source: string;
    target: string;
    weight: number;
    value: number;
    max_risk: number | null;
  }[];
};

/** Renders a value that may legitimately be absent, without faking a zero. */
export function val(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "\u2014";
  return n.toLocaleString("ro-MD", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  const raw = await res.text();
  if (!res.ok) {
    throw new Error(
      raw.slice(0, 300) || `${res.status} ${res.statusText} from ${url}`,
    );
  }
  if (!raw.trim()) {
    // The MTender API intermittently answers HTTP 200 with an empty body. If a
    // proxy ever passes that through, say so plainly instead of surfacing
    // "Unexpected end of JSON input" in the UI.
    throw new Error(`The API returned an empty body for ${url} (HTTP ${res.status}).`);
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new Error(`The API returned a malformed body for ${url}.`);
  }
}

export function mdl(n: number) {
  return new Intl.NumberFormat("ro-MD", {
    style: "currency",
    currency: "MDL",
    maximumFractionDigits: 0,
  }).format(n);
}

export function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

export function int(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "\u2014";
  return Math.round(n).toLocaleString("ro-MD");
}

/** Anomaly percentile: 0-100, one decimal, never a fabricated precision. */
export function pctile(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "\u2014";
  return n.toFixed(1);
}

/** "2024-03" -> "Mar 2024", for axis ticks and tooltips. */
export function monthLabel(m: string): string {
  const hit = /^(\d{4})-(\d{2})$/.exec(m);
  if (!hit) return m;
  const d = new Date(Date.UTC(Number(hit[1]), Number(hit[2]) - 1, 1));
  if (Number.isNaN(d.getTime())) return m;
  return d.toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });
}

export function dateLabel(s: string | null | undefined): string {
  if (!s) return "\u2014";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

/** Recharts axis/tooltip formatters, so charts never print raw float tails. */
export const num = (n: number) => int(n);
export const num1 = (n: number) => n.toFixed(1);
export const money = (n: number) => mdl(n);


/* ==========================================================================
   Analytics: distributions and correlations
   ========================================================================== */

export type FeatureMeta = {
  key: string;
  label: string;
  group: string;
  n: number;
  missing_rate: number | null;
  available: boolean;
  summary?: {
    min: number | null;
    p25: number | null;
    median: number | null;
    p75: number | null;
    max: number | null;
    mean: number | null;
    std: number | null;
    zeros: number;
  };
};

export type CategoryMeta = { key: string; label: string; n_levels: number };

export type FeatureCatalog = {
  features: FeatureMeta[];
  categories: CategoryMeta[];
  dates: Record<string, string>;
  min_pairs: number;
  n_rows: number;
};

export type CorrPair = {
  a: string;
  b: string;
  r: number;
  abs_r: number;
  direction: "positive" | "negative";
  n: number;
};

export type Correlations = {
  columns: string[];
  labels: string[];
  matrix: (number | null)[][];
  pairs: CorrPair[];
  n: number;
  method: string;
  min_pairs: number;
};

export type Bin = { x0: number | null; x1: number | null; mid: number | null; n: number };

export type DistSummary = {
  min: number | null;
  p25: number | null;
  median: number | null;
  p75: number | null;
  p90: number | null;
  p99: number | null;
  max: number | null;
  mean: number | null;
  std: number | null;
  iqr_outlier_rate: number;
  zeros: number;
  negative: number;
  n: number;
  skew_ratio: number | null;
};

export type Distribution = {
  column: string;
  label: string;
  bins: Bin[];
  /** [value, cumulative share] pairs, thinned server-side. */
  ecdf: [number, number][];
  summary: DistSummary | null;
  groups: {
    key: string;
    label: string;
    n: number;
    median: number | null;
    p25: number | null;
    p75: number | null;
    mean: number | null;
    share: number;
  }[];
  group_by: string | null;
  log_x: boolean;
  scale: "auto" | "linear" | "log" | "quantile";
};

export type ScatterPoint = { x: number; y: number; g: string | null };

export type ScatterData = {
  points: ScatterPoint[];
  x: string;
  y: string;
  x_label: string;
  y_label: string;
  group: string | null;
  fit: {
    slope: number;
    intercept: number;
    r: number | null;
    x_min: number;
    x_max: number;
  } | null;
  n: number;
  sampled: number;
};

export type GroupStats = {
  key: string;
  n: number;
  min: number | null;
  p25: number | null;
  median: number | null;
  p75: number | null;
  max: number | null;
  mean: number | null;
  outlier_rate: number;
};

export type GroupCompare = {
  value: string;
  value_label: string;
  group: string;
  group_label: string;
  groups: GroupStats[];
  n: number;
  dropped_groups: number;
};

export type Crosstab = {
  a: string;
  b: string;
  a_label: string;
  b_label: string;
  value: string | null;
  rows: string[];
  cols: string[];
  matrix: (number | null)[][];
  max: number | null;
  dropped: number;
};

export type TimeBucket = { period: string; value: number | null; n: number };

export type TimeGroupBucket = Record<string, number | string | null>;

export type TimeSeries = {
  buckets: (TimeBucket | TimeGroupBucket)[];
  grain: string;
  group: string | null;
  series: string[];
  date_field: string;
  value: string;
};

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const getFeatures = () => getJson<FeatureCatalog>("/api/analytics/features");

export const getCorrelations = (p: {
  features?: string[];
  method?: string;
  min_abs?: number;
  top?: number;
}) =>
  getJson<Correlations>(
    `/api/analytics/correlations${qs({
      features: p.features?.join(","),
      method: p.method,
      min_abs: p.min_abs,
      top: p.top,
    })}`,
  );

export const getDistribution = (p: {
  column: string;
  bins?: number;
  group?: string;
  log_x?: boolean;
  scale?: string;
}) =>
  getJson<Distribution>(
    `/api/analytics/distribution${qs({
      column: p.column,
      bins: p.bins,
      group: p.group,
      log_x: p.log_x,
      scale: p.scale,
    })}`,
  );

export const getScatter = (p: {
  x: string;
  y: string;
  group?: string;
  limit?: number;
  log_x?: boolean;
  log_y?: boolean;
}) =>
  getJson<ScatterData>(
    `/api/analytics/scatter${qs({
      x: p.x,
      y: p.y,
      group: p.group,
      limit: p.limit,
      log_x: p.log_x,
      log_y: p.log_y,
    })}`,
  );

export const getGroupCompare = (p: {
  value: string;
  group: string;
  limit?: number;
}) =>
  getJson<GroupCompare>(
    `/api/analytics/group-compare${qs({ value: p.value, group: p.group, limit: p.limit })}`,
  );

export const getCrosstab = (p: {
  a: string;
  b: string;
  value?: string;
  limit?: number;
}) =>
  getJson<Crosstab>(
    `/api/analytics/crosstab${qs({ a: p.a, b: p.b, value: p.value, limit: p.limit })}`,
  );

export const getTimeSeries = (p: {
  date_field?: string;
  grain?: string;
  group?: string;
  value?: string;
}) =>
  getJson<TimeSeries>(
    `/api/analytics/timeseries${qs({
      date_field: p.date_field,
      grain: p.grain,
      group: p.group,
      value: p.value,
    })}`,
  );

/* ==========================================================================
   Workspace CRUD
   ========================================================================== */

export type CaseRecord = {
  id: number;
  ref: string;
  title: string;
  status: string;
  priority: string;
  owner: string;
  summary: string;
  ocids: string;
  created_at: string;
  updated_at: string;
};

export type AnnotationRecord = {
  id: number;
  ocid: string;
  case_id: number | null;
  case_ref: string | null;
  case_title: string | null;
  category: string;
  note: string;
  author: string;
  created_at: string;
  updated_at: string;
};

export type Watchlist = {
  id: number;
  name: string;
  description: string;
  color: string;
  n_items: number;
  created_at: string;
  updated_at: string;
};

export type WatchItem = { id: number; watchlist_id: number; ocid: string; note: string; added_at: string };

export type SavedView = {
  id: number;
  name: string;
  description: string;
  payload: string;
  created_at: string;
  updated_at: string;
};

export type ActivityRecord = {
  id: number;
  at: string;
  entity: string;
  entity_id: number | null;
  action: string;
  detail: string;
};

export type WorkspaceSummary = {
  counts: {
    cases: number;
    annotations: number;
    watchlists: number;
    watchlist_items: number;
    saved_views: number;
  };
  cases_by_status: Record<string, number>;
  revision: number;
  db_path: string;
  vocab: {
    case_status: string[];
    case_priority: string[];
    annotation_category: string[];
    watchlist_colors: Record<string, string>;
  };
};

/** Verb wrapper. The body is JSON-encoded; errors keep the server's detail. */
export async function send<T>(
  method: "POST" | "PATCH" | "DELETE",
  url: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const raw = await res.text();
  if (!res.ok) {
    throw new Error(extractError(raw) || `${res.status} ${res.statusText} from ${url}`);
  }
  if (!raw.trim()) return undefined as T;
  return JSON.parse(raw) as T;
}

/** FastAPI validation errors are a list of {loc, msg}; flatten to one line. */
function extractError(raw: string): string {
  try {
    const parsed = JSON.parse(raw);
    const detail = parsed?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d: { loc?: (string | number)[]; msg?: string }) =>
          `${(d.loc ?? []).filter((p) => p !== "body").join(".")}: ${d.msg ?? ""}`.trim(),
        )
        .join("; ");
    }
  } catch {
    /* not JSON, fall through to the raw text */
  }
  return raw.slice(0, 300);
}

export const getWorkspaceSummary = () => getJson<WorkspaceSummary>("/api/workspace/summary");

export const getCases = (p: { status?: string; q?: string } = {}) =>
  getJson<{ items: CaseRecord[]; vocab: { status: string[]; priority: string[] } }>(
    `/api/workspace/cases${qs(p)}`,
  );

export const getCase = (id: number) =>
  getJson<{ case: CaseRecord; ocids: string[]; annotations: AnnotationRecord[] }>(
    `/api/workspace/cases/${id}`,
  );

export const createCase = (body: {
  title: string;
  status?: string;
  priority?: string;
  owner?: string;
  summary?: string;
  ocids?: string[] | string;
}) => send<CaseRecord>("POST", "/api/workspace/cases", body);

export const updateCase = (id: number, body: Record<string, unknown>) =>
  send<CaseRecord>("PATCH", `/api/workspace/cases/${id}`, body);

export const deleteCase = (id: number) =>
  send<{ deleted: number }>("DELETE", `/api/workspace/cases/${id}`);

export const getAnnotations = (p: { ocid?: string; case_id?: number; category?: string; q?: string } = {}) =>
  getJson<{ items: AnnotationRecord[]; vocab: { category: string[] } }>(
    `/api/workspace/annotations${qs(p)}`,
  );

export const createAnnotation = (body: {
  ocid: string;
  note: string;
  category?: string;
  case_id?: number | null;
  author?: string;
}) => send<AnnotationRecord>("POST", "/api/workspace/annotations", body);

export const updateAnnotation = (id: number, body: Record<string, unknown>) =>
  send<AnnotationRecord>("PATCH", `/api/workspace/annotations/${id}`, body);

export const deleteAnnotation = (id: number) =>
  send<{ deleted: number }>("DELETE", `/api/workspace/annotations/${id}`);

export const getWatchlists = () =>
  getJson<{ items: Watchlist[]; colors: Record<string, string> }>("/api/workspace/watchlists");

export const getWatchlist = (id: number) =>
  getJson<{ watchlist: Watchlist; items: WatchItem[] }>(`/api/workspace/watchlists/${id}`);

export const createWatchlist = (body: { name: string; description?: string; color?: string }) =>
  send<Watchlist>("POST", "/api/workspace/watchlists", body);

export const updateWatchlist = (id: number, body: Record<string, unknown>) =>
  send<Watchlist>("PATCH", `/api/workspace/watchlists/${id}`, body);

export const deleteWatchlist = (id: number) =>
  send<{ deleted: number }>("DELETE", `/api/workspace/watchlists/${id}`);

export const addWatchlistItems = (id: number, ocids: string[] | string, note = "") =>
  send<{ added: number; items: WatchItem[] }>("POST", `/api/workspace/watchlists/${id}/items`, {
    ocids,
    note,
  });

export const updateWatchlistItem = (itemId: number, note: string) =>
  send<{ updated: number }>("PATCH", `/api/workspace/watchlists/items/${itemId}`, { note });

export const deleteWatchlistItem = (itemId: number) =>
  send<{ deleted: number }>("DELETE", `/api/workspace/watchlists/items/${itemId}`);

export const getViews = () => getJson<{ items: SavedView[] }>("/api/workspace/views");

export const createView = (body: { name: string; description?: string; payload?: Record<string, unknown> }) =>
  send<SavedView>("POST", "/api/workspace/views", body);

export const updateView = (id: number, body: Record<string, unknown>) =>
  send<SavedView>("PATCH", `/api/workspace/views/${id}`, body);

export const deleteView = (id: number) => send<{ deleted: number }>("DELETE", `/api/workspace/views/${id}`);

export const getActivity = (limit = 25) =>
  getJson<{ items: ActivityRecord[] }>(`/api/workspace/activity${qs({ limit })}`);

export const resetWorkspace = () => send<WorkspaceSummary>("POST", "/api/workspace/reset?confirm=true");
