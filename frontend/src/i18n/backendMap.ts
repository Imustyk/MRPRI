import i18n from "./index";

/**
 * The FastAPI backend serves English labels (feature names, red-flag labels,
 * KPI check labels, HTTP error details) that the UI renders verbatim. Rather
 * than change the API, the frontend keeps a map from those exact English
 * strings to i18n keys and falls back to the raw English when a string has no
 * entry — so a new backend label degrades gracefully instead of breaking.
 *
 * Usage: `tr(row.label)` at any point where a server string is about to be
 * rendered. Interpolated labels (built server-side with f-strings) are matched
 * by regex and re-interpolated into the localised template.
 */
const MAP: Record<string, string> = {
  // ---- adapter.py red flags ----
  "Single bidder": "backend.flag.single_bidder",
  "Short bidding window": "backend.flag.short_window",
  "Accelerated procedure": "backend.flag.accelerated",
  "No award published after tender": "backend.flag.no_award",
  "Award split into many lots": "backend.flag.split_lots",
  "Several suppliers on one award": "backend.flag.several_suppliers",
  "Cancelled": "backend.flag.cancelled",
  "Amended after publication": "backend.flag.amended",
  "No bid data published": "backend.flag.no_bid_data",
  "Long bidding window": "backend.flag.long_window",

  // ---- analytics.py feature labels ----
  "Award total (MDL)": "backend.feature.award_total",
  "First award value (MDL)": "backend.feature.first_award",
  "Estimated value (MDL)": "backend.feature.estimated",
  "Award / estimate ratio": "backend.feature.award_estimate_ratio",
  "Value vs CPV median": "backend.feature.value_vs_cpv",
  "Distinct bidders": "backend.feature.distinct_bidders",
  "Bid records (per lot)": "backend.feature.bid_records",
  "Lots": "backend.feature.lots",
  "Awards": "backend.feature.awards",
  "Bidding window (days)": "backend.feature.bidding_window",
  "Single bidder (0/1)": "backend.feature.single_bidder_01",
  "Short deadline (0/1)": "backend.feature.short_deadline_01",
  "Winner share of buyer awards": "backend.feature.winner_share",
  "Repeat pair share": "backend.feature.repeat_pair",
  "Anomaly percentile": "backend.feature.anomaly_percentile",
  "Isolation Forest score": "backend.feature.iforest_score",
  "LOF score": "backend.feature.lof_score",
  "One-Class SVM score": "backend.feature.svm_score",
  "MAD z-score": "backend.feature.mad_z",

  // ---- feature group headers ----
  "financial": "backend.group.financial",
  "competition": "backend.group.competition",
  "procedural": "backend.group.procedural",
  "behavioural": "backend.group.behavioural",
  "model": "backend.group.model",

  // ---- grouping-variable categories ----
  "Risk band": "backend.category.risk_band",
  "Procedure type": "backend.category.procedure_type",
  "Procurement method": "backend.category.procurement_method",
  "Status": "backend.category.status",
  "Procurer locality": "backend.category.locality",
  "CPV code": "backend.category.cpv",
  "Procurer": "backend.category.procurer",
  "Supplier": "backend.category.supplier",

  // ---- date fields ----
  "Published": "backend.date.published",
  "Listed": "backend.date.listed",
  "Tender start": "backend.date.tender_start",
  "Bidding deadline": "backend.date.deadline",
  "Award date": "backend.date.award_date",

  // ---- model_kpis.py detectors ----
  "MAD z-score baseline": "backend.detector.mad",
  "Isolation Forest": "backend.detector.iforest",
  "Local Outlier Factor": "backend.detector.lof",
  "One-Class SVM": "backend.detector.ocsvm",

  // ---- detector families ----
  "robust univariate statistics": "backend.family.robust",
  "tree ensemble": "backend.family.ensemble",
  "neighbourhood density": "backend.family.neighbourhood",
  "kernel density": "backend.family.kernel",

  // ---- store.py risk-band meanings (meta.risk_bands values) ----
  "no detector output exists for this record (not a clearance)": "backend.band.unscored",
  "no model flagged the record": "backend.band.low",
  "1 model flagged it": "backend.band.medium",
  "2 models flagged it": "backend.band.high",
  "3 or more models flagged it (consensus)": "backend.band.critical",

  // ---- meta: source / metrics / unavailable reasons ----
  "mtender-ocds (real public procurement data)": "backend.meta.source",
  "real procurements have no planted-anomaly ground truth, so precision/recall/F1 are not computable on this corpus; the checks verify verdicts, thresholds, counts and artefact paths instead":
    "backend.meta.metrics_reason",
  // /api/stats serves the short form of the same sentence.
  "real procurements have no planted-anomaly ground truth": "backend.meta.metrics_reason_short",
  "MTender publishes CPV codes only; no code->label dictionary is served": "backend.meta.unavailable_cpv",
  "bids.details is published for a small minority of procurements only": "backend.meta.unavailable_bids",
  "derived from bid-level prices, which are mostly absent": "backend.meta.unavailable_bid_prices",
  "requires both bid prices and the estimated value per lot": "backend.meta.unavailable_lot_ratio",
  "no direct-award indicator in the OCDS payload": "backend.meta.unavailable_direct",
  "no negotiated-procedure flag in the OCDS payload": "backend.meta.unavailable_negotiated",
  "not derivable from a single aggregate award amount": "backend.meta.unavailable_aggregate",
  "threshold proximity needs the per-procedure limit, which is not published": "backend.meta.unavailable_threshold",
  "party registration dates are not in the payload": "backend.meta.unavailable_dates",
  "bids.details is per-lot, so this counts bid records, not bidders": "backend.meta.unavailable_bid_records",
  "ground-truth label, synthetic data only": "backend.meta.unavailable_truth",
  "(unknown)": "backend.meta.unknown",

  // ---- model_kpis.py static check labels ----
  "Verdict stored for every scored row": "backend.kpi.verdict_stored",
  "Scores agree with the verdict": "backend.kpi.scores_agree",
  "Declared model path resolves to the artefact": "backend.kpi.path_resolves",
  "Corpus carries detector output": "backend.kpi.corpus_output",
  "n_models_flagging equals the number of set verdicts": "backend.kpi.counts_equal",
  "Anomaly percentile stays within 0-100": "backend.kpi.percentile_bounds",
  "Live flagged shares match the recorded detection run": "backend.kpi.run_repro",

  // ---- workspace case status / priority (also used as option labels) ----
  open: "vocab.status_open",
  "in review": "vocab.status_in_review",
  escalated: "vocab.status_escalated",
  closed: "vocab.status_closed",
  dismissed: "vocab.status_dismissed",
  low: "vocab.priority_low",
  medium: "vocab.priority_medium",
  high: "vocab.priority_high",
  critical: "vocab.priority_critical",
  positive: "vocab.positive",
  negative: "vocab.negative",

  // ---- workspace annotation categories ----
  "observation": "backend.annot.observation",
  "single bidder": "backend.annot.single_bidder",
  "repeat relationship": "backend.annot.repeat",
  "value anomaly": "backend.annot.value",
  "documentation gap": "backend.annot.docs",
  "follow-up": "backend.annot.followup",
  "cleared": "backend.annot.cleared",

  // ---- HTTP error details (main.py + workspace_api.py) ----
  "Run the pipeline first": "backend.err.run_pipeline",
  "Tender not found": "backend.err.tender_not_found",
  "source must be 'synthetic' or 'ocds'": "backend.err.source_invalid",
  "Case not found": "backend.err.case_not_found",
  "Annotation not found": "backend.err.annotation_not_found",
  "Watchlist not found": "backend.err.watchlist_not_found",
  "Item not found": "backend.err.item_not_found",
  "View not found": "backend.err.view_not_found",
  "Pass confirm=true to delete all workspace rows": "backend.err.confirm_reset",
  "method must be pearson, spearman or kendall": "backend.err.method_invalid",
  "scale must be auto, linear, log or quantile": "backend.err.scale_invalid",
  "grain must be day, week, month, quarter or year": "backend.err.grain_invalid",

  // ---- /api/evaluation: external proxy labels (labels + static caveats) ----
  "AAP supplier interdiction list (proxy label)": "backend.ext.aap_label",
  "Procedure contested (ANSC complaints document; proxy label)": "backend.ext.ansc_label",
  "Proxy label: procedures of sanctioned suppliers, not ground truth. The label is driven by size and competition (single-feature n_bidders baseline ~0.80); the 4-vote ensemble at ~0.49 is at random level - reported as measured.":
    "backend.ext.aap_caveat",
  "Complaints are a contested-procedure marker, not a confirmed violation: ANSC decisions were not accessible for this corpus, so confirmed vs rejected appeals cannot be distinguished.":
    "backend.ext.ansc_caveat",
  // Served in Russian by the methodology artefact.
  "ДИ включает 0,5 — на этой метке сигнал неотличим от случайного":
    "backend.ext.ansc_verdict",
  "Input-noise experiment (measurement, not a cycle): score ranks are stable for exact/near-exact inputs but positions move under counterfactual noise; review top-K lists, not exact ranks.":
    "backend.eval.noise_note",
  "Score-distribution drift between tune (2018-2021) and test (2022-2024): the vote boundary needs periodic recalibration.":
    "backend.eval.drift_note",
  "Indicators of potential risk, not evidence of corruption.": "backend.eval.disclaimer",
  // ---- bias audit verdict words (served in Russian) ----
  "допустимо": "backend.bias.admissible",
  "допустимо (разница объяснена легитимными факторами)": "backend.bias.admissible_explained",
  "нарушение": "backend.bias.violation",
  "предупреждение": "backend.bias.warning",

  // ---- /api/explainability: measured SHAP vs LIME disagreement ----
  "не согласованы": "backend.xai.verdict_disagree",
  "Индикатор потенциального риска, а не доказательство коррупции. Разбор методов объяснения, а не оценка процедуры.":
    "backend.xai.disclaimer",
  "SHAP values here are computed for the Isolation Forest only; LOF, One-Class SVM and MAD have no per-row attributions.":
    "backend.xai.note_shap_only",
  "SHAP and LIME disagree on this model (see xai_consistency.verdict); treat attributions as model-internal, not causal.":
    "backend.xai.note_disagree",

  // ---- dataset provenance: model label ----
  "v0 production: MAD robust z-score + IsolationForest + LOF + One-Class SVM (4-vote consensus)":
    "backend.model.production_label",

  // ---- explain.py: static limitations and reference labels ----
  "Anomaly score = indicator of potential risk, not evidence of corruption or violation. Verification by a competent authority is required.":
    "backend.explain.disclaimer",
  "Explanations are model-internal reasons for an unusual score; they are not causal proof of any wrongdoing.":
    "backend.explain.not_causal",
  "Per-row attributions exist only for the Isolation Forest; LOF, One-Class SVM and MAD have verdicts but no per-row attribution.":
    "backend.explain.per_row_only",
  "Score ranks below the top-200 are noise-sensitive (input-noise audit); review lists of cases, not exact positions.":
    "backend.explain.top200",
  "Fields MTender does not publish are shown as unavailable, never imputed.":
    "backend.explain.not_imputed",
  "This record was never scored by the detection run - it is not examined, and 'unscored' is not a clearance.":
    "backend.explain.never_scored",
  "Global explainability (permutation importance, SHAP, SHAP vs LIME)": "backend.explain.ref_global",
  "Permutation importance (all 22 features)": "backend.explain.ref_perm",
  "SHAP feature importance (Isolation Forest only)": "backend.explain.ref_shap",
  "SHAP vs LIME consistency measurement": "backend.explain.ref_xai",
  "Input-noise sensitivity of score ranks": "backend.explain.ref_noise",
  "Model card (MTA-0004)": "backend.explain.ref_card",
};

/**
 * Interpolated KPI check labels, built server-side with f-strings. Matched by
 * regex; the captured groups are re-interpolated into the localised template.
 */
const PATTERNS: { re: RegExp; key: string; vars: string[] }[] = [
  // "Flagged share inside the contamination band (contamination)" / "(z_threshold)"
  {
    re: /^Flagged share inside the contamination band \((.+)\)$/,
    key: "backend.kpi.flagged_share",
    vars: ["name"],
  },
  // "Flag reproduces the declared z_threshold"
  {
    re: /^Flag reproduces the declared (.+)$/,
    key: "backend.kpi.flag_reproduces",
    vars: ["name"],
  },
  // "consensus == (n_models_flagging >= 3)"
  {
    re: /^consensus == \(n_models_flagging >= (\d+)\)$/,
    key: "backend.kpi.consensus",
    vars: ["min"],
  },
  // explain.py: the SHAP/LIME disagreement limitation, verdict interpolated.
  {
    re: /^SHAP and LIME disagree on this model \(measured verdict: "(.+)"\); treat single attributions with caution\.$/,
    key: "backend.explain.shap_lime_disagree",
    vars: ["verdict"],
  },
  // explain.py: the dynamic "missing fields" tail of the limitations layer.
  {
    re: /^Not present in this record: (.+)$/,
    key: "backend.explain.not_present",
    vars: ["fields"],
  },
];

/** One exact map pass, so captured verdicts localise inside a template. */
function localise(s: string): string {
  const key = MAP[s];
  if (!key) return s;
  const out = i18n.t(key);
  return out === key ? s : out;
}

/**
 * Translate a server-supplied English string. Falls back to the input when
 * there is no mapping, so unknown/new backend labels still render (in English)
 * rather than showing a raw i18n key.
 */
export function tr(s: string | null | undefined): string {
  if (!s) return s ?? "";
  const key = MAP[s];
  if (key) {
    const out = i18n.t(key);
    // i18n.t returns the key itself when missing — treat that as "no mapping".
    if (out !== key) return out;
  }
  for (const { re, key: pkey, vars } of PATTERNS) {
    const m = re.exec(s);
    if (m) {
      const opts: Record<string, string> = {};
      vars.forEach((v, i) => (opts[v] = localise(m[i + 1])));
      const out = i18n.t(pkey, opts);
      if (out !== pkey) return out;
    }
  }
  return s;
}

/** True when a server string has a localisation, for conditional rendering. */
export function trHas(s: string): boolean {
  return MAP[s] !== undefined;
}
