const analysis = {
  "platform": "Procurement research workspace",
  "models_title": "Model analysis",
  "indicators_title": "Risk indicators",
  "models_intro": "Inspect stored model decisions, compare scores within the same run, and trace the evidence behind each procedure.",
  "indicators_intro": "Measured indicators, calculation logic and data limitations. Rules and model outputs are kept separate.",
  "select_procedure": "Select a procedure",
  "find_procedure": "Find a procedure",
  "search_hint": "Title, buyer, supplier or OCID",
  "open_case": "Open full analysis",
  "picker_scope": "Up to 20 matches, ranked by the existing anomaly percentile. This list is a selector, not the model reference population.",
  "no_results": "No matching procedures",
  "selected_procedure": "Selected procedure",
  "model_explanation": "Model evidence",
  "flagged": "Flagged",
  "not_flagged": "Not flagged",
  "unavailable": "No data",
  "raw_score": "Raw model score",
  "score_rank": "Raw-score percentile",
  "rank_definition": "Midrank of ties, same run; not probability",
  "reference_size": "Reference observations",
  "same_run": "Available scores from the same identified run",
  "score_distribution": "Model score distribution",
  "log_counts": "log10(1 + count)",
  "hist_scope": "Scope: {{n}} finite scores, {{missing}} missing; run {{run}}.",
  "hist_a11y": "Score distribution for {{name}}. Selected score: {{value}}. Exact intervals are in the table.",
  "procedures": "Procedure count",
  "score_intervals": "Raw-score intervals",
  "selected_interval": "Interval containing the selected procedure",
  "threshold_interval": "Interval containing the stored boundary",
  "y_log": "Vertical axis: log10(1 + count), ticks show counts",
  "y_count": "Vertical axis: procedure count",
  "bin_note": "Markers identify histogram intervals, not exact geometric locations. The exact score and boundary are shown numerically.",
  "reference_unavailable": "A comparable reference is unavailable",
  "reference_reason": "No confirmed run identity or no finite scores. A different run is never substituted.",
  "threshold": "Confirmed score boundary",
  "source": "Source",
  "threshold_mismatch": "The saved flag disagrees with the documented boundary. The flag has not been rewritten; verify the source.",
  "features_parameters": "Features, parameters and limits",
  "features": "Recorded model features",
  "parameters": "Recorded parameters",
  "no_attribution": "Training medians/MAD and local feature contributions are not supplied here. Global feature importance is not a per-procedure attribution. Contamination/nu is not a raw-score threshold.",
  "distribution_table": "Inspect exact histogram counts",
  "selection": "Selection",
  "run": "Run",
  "version": "Reported version",
  "explainability_first": "Understand before interpreting",
  "compare_models": "Four models. Four different scales.",
  "votes": "Saved flagged count",
  "relative_rank": "Aggregate relative percentile",
  "consensus": "Saved consensus flag",
  "yes": "Yes",
  "no": "No",
  "voting_note": "Band and vote count are taken from the API. The current documented policy is 0 low, 1 medium, 2 high, 3–4 critical. Missing verdicts remain unknown. Aggregate percentile is not corruption probability or a legal finding.",
  "run_unverified": "Run identity or its parameter summary is not confirmed. Missing thresholds and parameters have not been reconstructed.",
  "scales_note": "Each raw score has its own scale. Select a model to inspect it separately.",
  "model": "Model",
  "verdict": "Stored decision",
  "details": "Details",
  "inspect": "Inspect model",
  "agreement_title": "How often do model decisions agree?",
  "agreement_scope": "Same run {{run}}: {{n}} procedures. Each cell excludes missing verdicts for its pair.",
  "agreement_definition": "Agreement = matching decisions / pairs with both decisions. This includes shared non-flags and is not external accuracy.",
  "separate_rules": "Measured features · separate from detectors",
  "indicators_note": "Values come from the current ETL snapshot. An available derived value can contain imputation and does not certify source completeness or availability at publication.",
  "indicator_group": "Indicator group",
  "source_missing": "Source data missing",
  "derived_unverified": "Derived · incomplete inputs",
  "stored_value": "Stored ETL value",
  "recorded_signal": "Recorded signal",
  "formula_quality": "Calculation and data quality",
  "formula": "Calculation in the existing ETL",
  "inputs": "Source fields",
  "etl_value": "Stored derived value",
  "no_indicator_threshold": "No independent continuous-score warning threshold is supplied for this indicator. A value alone is not a violation.",
  "additional_rules": "Other recorded rules and specialized modules",
  "additional_rules_note": "Only signals actually present in flags are listed. Absence from this list does not establish a negative result when the original field is unavailable.",
  "no_recorded_signals": "No signals recorded; data completeness still needs checking.",
  "specialized_unavailable": "Specialized research modules without per-procedure API output are methodological references, not additional calculated signals on this page.",
  "disclaimer": "An anomaly warrants further analysis. It is not proof of corruption, collusion or a legal violation.",
  "case_sections": "Analysis sections",
  "facts": "Procedure facts",
  "evidence": "Evidence and provenance",
  "package_date": "OCDS package date",
  "bid_data_available": "Bid data published",
  "bid_data_missing": "Bid data unavailable",
  "award_data_available": "Award data available",
  "award_data_missing": "Award data unavailable",
  "additional_facts": "Additional facts and source limits",
  "days": "days",
  "raw_facts_limit": "Stored feature values may use ETL defaults. Package dates are not a certified first notice; historical publication-time availability remains unverified.",
  "loading_models": "Loading saved model evidence…",
  "traceability": "Trace every conclusion",
  "run_date": "Recorded run date",
  "reference_present": "File available",
  "not_recorded": "Signal not recorded",
  "corpus_frequency": "Corpus frequency",
  "explanation_unavailable": "Legacy explanation layers are unavailable. Available model evidence is shown separately above.",
  "peer_limit": "The model reference is the same-run scored population, not a matched set of similar procurements. No causal or matched-peer claim is made.",
  "theme_light": "Light appearance",
  "theme_dark": "Dark appearance",
  "theme_toggle": "Switch appearance",
  "research": "Research",
  "close_menu": "Close navigation",
  "coverage_decisions": "Available model decisions",
  "groups": {
    "all": "All",
    "financial": "Financial",
    "competition": "Competition",
    "procedural": "Procedural",
    "behavioural": "Behavioural"
  },
  "models": {
    "statistical_mad_zscore": {
      "description": "Robust deviation from typical feature values, aggregated as the maximum absolute normalized deviation.",
      "limitation": "Training medians/MAD were not saved. Feature-level deviations cannot be reconstructed here. Binary and spike-like features were excluded according to the recorded run."
    },
    "isolation_forest": {
      "description": "Isolation Forest scores how readily an observation can be isolated. The stored score is negative score_samples: larger values indicate greater anomaly.",
      "limitation": "No actual trees or local attributions are supplied. A population histogram explains position, not which feature caused the decision. Contamination is not a score boundary."
    },
    "local_outlier_factor": {
      "description": "LOF compares local density to the fitted neighbourhood. Stored negative score_samples grows with local abnormality.",
      "limitation": "Neighbour identities, training geometry and fitted offset are not saved in this API. No synthetic neighbourhood or 2D map is drawn."
    },
    "one_class_svm": {
      "description": "One-Class SVM estimates a boundary in the model feature space. Stored score = −decision_function; positive values lie on the anomaly side of the documented zero boundary.",
      "limitation": "The boundary is shown numerically only when run provenance matches. No arbitrary two-dimensional separator is presented as the fitted multidimensional model."
    }
  },
  "indicators": {
    "value_vs_cpv_median": {
      "title": "Value / CPV median",
      "description": "First award value relative to the CPV group median in the ETL frame.",
      "limitation": "Missing ratios become 1 and extreme ratios are clipped at 20. This is a derived value, not an original price benchmark."
    },
    "estimate_to_award_ratio": {
      "title": "Estimate / awarded total",
      "description": "Estimate divided by the all-lot awarded total, with primary award fallback.",
      "limitation": "The code uses estimate / award, despite an older API label saying the reverse. Missing becomes 1, values clip to [0,20]."
    },
    "n_bidders": {
      "title": "Distinct bidders",
      "description": "Participant count provided by the existing ETL, separate from per-lot bid records.",
      "limitation": "Zero without published bid data does not prove no competition."
    },
    "single_bidder": {
      "title": "Single bidder",
      "description": "Stored binary indicator: participant count equals one.",
      "limitation": "A missing participant list cannot establish a negative single-bidder finding."
    },
    "bid_window_days": {
      "title": "Bidding window",
      "description": "Whole-day difference between the tender period end and start in the existing ETL.",
      "limitation": "Missing becomes 30 days. PN/EV mixing and historical availability remain unresolved; this is not certified publication-time evidence."
    },
    "short_deadline": {
      "title": "Short deadline",
      "description": "Stored rule: bidding window is nonnegative and shorter than seven days.",
      "limitation": "The rule inherits the window imputation and provenance limits; it is not a legal finding."
    },
    "buyer_supplier_repeat_share": {
      "title": "Repeat pair share",
      "description": "Awarded procedures for this buyer–winner pair divided by awarded procedures for the buyer.",
      "limitation": "Calculated over the available frame, not a historical snapshot. The current code equals winner_share_of_buyer_awards; these are not independent signals."
    },
    "winner_share_of_buyer_awards": {
      "title": "Winner share at the buyer",
      "description": "The same pair-to-buyer awarded-procedure share stored by the current ETL.",
      "limitation": "Defaults can be zero. This equals the repeat-pair share in the current implementation and does not independently confirm it."
    }
  }
};

export default analysis;
