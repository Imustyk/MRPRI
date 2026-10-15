/**
 * Shared vocabulary: chrome used by App/ui, HTTP error templates, and the
 * generic bits every page reaches for. English is the source locale — every
 * other catalog is shaped after this file (`typeof en`).
 *
 * Plural keys: when a string is counted, the catalog carries _one/_few/_many/
 * _other in all three locales (English never requests _few/_many, but keeping
 * the shape identical lets TypeScript enforce completeness).
 */
const en = {
  nav: {
    group_analysis: "Analysis",
    group_thesis: "Thesis",
    overview: "Overview",
    procedures: "Procedures",
    distributions: "Distributions",
    network: "Buyer–winner network",
    workspace: "Workspace",
    methodology: "Methodology",
    kpis: "Model KPI",
    raci: "RACI matrix",
    primary: "Primary",
  },
  brand: {
    name_a: "MTender",
    name_b: "Risk",
    doc_title: "MTender Risk Intelligence",
    doc_desc:
      "Anomaly detection over real Moldova public procurement data from the MTender OCDS feed.",
    tagline: "Anomaly detection for Moldova public procurement",
    foot_1: "Master's application · Law 131/2015 · Isolation Forest + red flags",
    foot_2: "Scores are risk indicators, not legal findings.",
    skip: "Skip to content",
  },
  lang: {
    label: "Language",
  },
  common: {
    loading: "Loading",
    could_not_load: "Could not load this view.",
    retry: "Retry",
    confirm_delete: "Confirm delete",
    cancel: "Cancel",
    save: "Save",
    create: "Create",
    delete: "Delete",
    edit: "Edit",
    close: "Close",
    search: "Search",
    apply: "Apply",
    reset: "Reset",
    all: "All",
    none: "None",
    yes: "Yes",
    no: "No",
    of: "of",
    and: "and",
    table_scrollable: "Data table, scrollable",
    empty_value: "—",
  },
  risk: {
    unscored: "not scored",
    low: "low",
    medium: "medium",
    high: "high",
    critical: "critical",
    detectors_one: "{{count}}/4 detector",
    detectors_few: "{{count}}/4 detectors",
    detectors_many: "{{count}}/4 detectors",
    detectors_other: "{{count}}/4 detectors",
  },
  vocab: {
    // Backend vocabulary rendered verbatim as pills/options (see backendMap).
    status_open: "open",
    status_in_review: "in review",
    status_escalated: "escalated",
    status_closed: "closed",
    status_dismissed: "dismissed",
    priority_low: "low",
    priority_medium: "medium",
    priority_high: "high",
    priority_critical: "critical",
    buyer: "buyer",
    supplier: "supplier",
    pass: "pass",
    fail: "fail",
    skip: "not applicable",
    positive: "positive",
    negative: "negative",
    flagged: "flagged",
    cleared: "cleared",
    never_examined: "never examined",
  },
  api: {
    http_error: "{{status}} {{statusText}} from {{url}}",
    empty_body: "The API returned an empty body for {{url}} (HTTP {{status}}).",
    malformed_body: "The API returned a malformed body for {{url}}.",
    bad_json: "Payload is not valid JSON: {{err}}",
  },
};

export default en;
