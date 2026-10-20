/**
 * Backend-sourced strings: the FastAPI app serves English labels (feature
 * names, red-flag labels, KPI check labels, HTTP error details) that the UI
 * renders verbatim. These namespaces let the UI localise them. The English
 * catalog doubles as the fallback when a string has no translation.
 */
const backend = {
  flag: {
    single_bidder: "Single bidder",
    short_window: "Short bidding window",
    accelerated: "Accelerated procedure",
    no_award: "No award published after tender",
    split_lots: "Award split into many lots",
    several_suppliers: "Several suppliers on one award",
    cancelled: "Cancelled",
    amended: "Amended after publication",
    no_bid_data: "No bid data published",
    long_window: "Long bidding window",
  },
  feature: {
    award_total: "Award total (MDL)",
    first_award: "First award value (MDL)",
    estimated: "Estimated value (MDL)",
    award_estimate_ratio: "Award / estimate ratio",
    value_vs_cpv: "Value vs CPV median",
    distinct_bidders: "Distinct bidders",
    bid_records: "Bid records (per lot)",
    lots: "Lots",
    awards: "Awards",
    bidding_window: "Bidding window (days)",
    single_bidder_01: "Single bidder (0/1)",
    short_deadline_01: "Short deadline (0/1)",
    winner_share: "Winner share of buyer awards",
    repeat_pair: "Repeat pair share",
    anomaly_percentile: "Anomaly percentile",
    iforest_score: "Isolation Forest score",
    lof_score: "LOF score",
    svm_score: "One-Class SVM score",
    mad_z: "MAD z-score",
  },
  group: {
    financial: "financial",
    competition: "competition",
    procedural: "procedural",
    behavioural: "behavioural",
    model: "model",
  },
  category: {
    risk_band: "Risk band",
    procedure_type: "Procedure type",
    procurement_method: "Procurement method",
    status: "Status",
    locality: "Procurer locality",
    cpv: "CPV code",
    procurer: "Procurer",
    supplier: "Supplier",
  },
  date: {
    published: "Published",
    listed: "Listed",
    tender_start: "Tender start",
    deadline: "Bidding deadline",
    award_date: "Award date",
  },
  detector: {
    mad: "MAD z-score baseline",
    iforest: "Isolation Forest",
    lof: "Local Outlier Factor",
    ocsvm: "One-Class SVM",
  },
  family: {
    robust: "robust univariate statistics",
    ensemble: "tree ensemble",
    neighbourhood: "neighbourhood density",
    kernel: "kernel density",
  },
  band: {
    unscored: "no detector output exists for this record (not a clearance)",
    low: "no model flagged the record",
    medium: "1 model flagged it",
    high: "2 models flagged it",
    critical: "3 or more models flagged it (consensus)",
  },
  meta: {
    source: "mtender-ocds (real public procurement data)",
    metrics_reason:
      "real procurements have no planted-anomaly ground truth, so precision/recall/F1 are not computable on this corpus; the checks verify verdicts, thresholds, counts and artefact paths instead",
    metrics_reason_short: "real procurements have no planted-anomaly ground truth",
    unavailable_cpv: "MTender publishes CPV codes only; no code->label dictionary is served",
    unavailable_bids: "bids.details is published for a small minority of procurements only",
    unavailable_bid_prices: "derived from bid-level prices, which are mostly absent",
    unavailable_lot_ratio: "requires both bid prices and the estimated value per lot",
    unavailable_direct: "no direct-award indicator in the OCDS payload",
    unavailable_negotiated: "no negotiated-procedure flag in the OCDS payload",
    unavailable_aggregate: "not derivable from a single aggregate award amount",
    unavailable_threshold: "threshold proximity needs the per-procedure limit, which is not published",
    unavailable_dates: "party registration dates are not in the payload",
    unavailable_bid_records: "bids.details is per-lot, so this counts bid records, not bidders",
    unavailable_truth: "ground-truth label, synthetic data only",
    unknown: "(unknown)",
  },
  kpi: {
    verdict_stored: "Verdict stored for every scored row",
    flagged_share: "Flagged share inside the contamination band ({{name}})",
    flag_reproduces: "Flag reproduces the declared {{name}}",
    scores_agree: "Scores agree with the verdict",
    path_resolves: "Declared model path resolves to the artefact",
    corpus_output: "Corpus carries detector output",
    counts_equal: "n_models_flagging equals the number of set verdicts",
    consensus: "consensus == (n_models_flagging >= {{min}})",
    percentile_bounds: "Anomaly percentile stays within 0-100",
    run_repro: "Live flagged shares match the recorded detection run",
  },
  annot: {
    observation: "observation",
    single_bidder: "single bidder",
    repeat: "repeat relationship",
    value: "value anomaly",
    docs: "documentation gap",
    followup: "follow-up",
    cleared: "cleared",
  },
  ext: {
    aap_label: "AAP supplier interdiction list (proxy label)",
    ansc_label: "Procedure contested (ANSC complaints document; proxy label)",
    aap_caveat:
      "Proxy label: procedures of sanctioned suppliers, not ground truth. The label is driven by size and competition (single-feature n_bidders baseline ~0.80); the 4-vote ensemble at ~0.49 is at random level — reported as measured.",
    ansc_caveat:
      "Complaints are a contested-procedure marker, not a confirmed violation: ANSC decisions were not accessible for this corpus, so confirmed vs rejected appeals cannot be distinguished.",
    ansc_verdict: "The 95% CI includes 0.5 — on this label the signal is indistinguishable from random",
  },
  eval: {
    noise_note:
      "Input-noise experiment (a measurement, not an acceptance cycle): score ranks are stable for exact and near-exact inputs, but positions move under counterfactual noise — review top-K lists, not exact ranks.",
    drift_note:
      "Score-distribution drift between the tuning period (2018–2021) and the test period (2022–2024): the vote boundary needs periodic recalibration.",
    disclaimer: "Indicators of potential risk, not evidence of corruption.",
  },
  bias: {
    admissible: "admissible",
    admissible_explained: "admissible (difference explained by legitimate factors)",
    violation: "violation",
    warning: "warning",
  },
  xai: {
    verdict_disagree: "not consistent",
    disclaimer:
      "Indicator of potential risk, not evidence of corruption. An analysis of explanation methods, not an assessment of the procedure.",
    note_shap_only:
      "SHAP values here are computed for the Isolation Forest only; LOF, One-Class SVM and MAD have no per-row attributions.",
    note_disagree:
      "SHAP and LIME disagree on this model (see xai_consistency.verdict); treat attributions as model-internal, not causal.",
  },
  model: {
    production_label:
      "v0 production: MAD robust z-score + IsolationForest + LOF + One-Class SVM (4-vote consensus)",
  },
  explain: {
    disclaimer:
      "An anomaly score is an indicator of potential risk, not evidence of corruption or violation. Verification by a competent authority is required.",
    not_causal:
      "Explanations are model-internal reasons for an unusual score; they are not causal proof of any wrongdoing.",
    shap_lime_disagree:
      "SHAP and LIME disagree on this model (measured verdict: “{{verdict}}”); treat single attributions with caution.",
    per_row_only:
      "Per-row attributions exist only for the Isolation Forest; LOF, One-Class SVM and MAD have verdicts but no per-row attribution.",
    top200:
      "Ranks below the top-200 are noise-sensitive (input-noise audit); review lists of cases, not exact positions.",
    not_imputed:
      "Fields MTender does not publish are shown as unavailable, never imputed.",
    never_scored:
      "This record was never scored by the detection run — it was not examined, and “not scored” is not a clearance.",
    not_present: "Not present in this record: {{fields}}",
    ref_global: "Global explainability (permutation importance, SHAP, SHAP vs LIME)",
    ref_perm: "Permutation importance (all 22 features)",
    ref_shap: "SHAP feature importance (Isolation Forest only)",
    ref_xai: "SHAP vs LIME consistency measurement",
    ref_noise: "Input-noise sensitivity of score ranks",
    ref_card: "Model card (MTA-0004)",
  },
  err: {
    run_pipeline: "Run the pipeline first",
    tender_not_found: "Tender not found",
    source_invalid: "source must be 'synthetic' or 'ocds'",
    case_not_found: "Case not found",
    annotation_not_found: "Annotation not found",
    watchlist_not_found: "Watchlist not found",
    item_not_found: "Item not found",
    view_not_found: "View not found",
    confirm_reset: "Pass confirm=true to delete all workspace rows",
    method_invalid: "method must be pearson, spearman or kendall",
    scale_invalid: "scale must be auto, linear, log or quantile",
    grain_invalid: "grain must be day, week, month, quarter or year",
  },
};

export default backend;
