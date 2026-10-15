/**
 * Method page strings (English = source). Prose that embeds <code> or <Link>
 * uses react-i18next <Trans>, so the markup lives in the string as named tags
 * (<code>, <racilink>, <kpilink>) and word order can differ per language.
 */
const method = {
  kicker: "Thesis mapping",
  title: "How the detector is built",
  lede: `The dashboard is a read-only view over the ETL in <code>/scripts</code>. Every number it shows comes from the real MTender OCDS feed stored in MongoDB, not from generated data. Who may change that methodology is on the <racilink>RACI matrix</racilink>.`,
  pipeline_h: "Pipeline",
  pipeline: {
    step1: `Walk the whole public OCID history (<code>01a</code>) and fetch one OCDS package per procedure (<code>01b</code>), keeping the exact response body in an archive so any result can be recomputed.`,
    step2: `Normalise and validate (<code>02</code>): resolve the buyer from <code>parties[].roles</code> because the top-level <code>buyer</code> is never populated, read CPV from both <code>tender.classification</code> and <code>tender.items[].classification</code>, and accept both address layouts.`,
    step3: `Engineer indicators in SQL and pandas (<code>03</code>), with the MongoDB and pandas definitions of the CPV median cross-checked against each other.`,
    step4: `Score with four independent detectors (<code>06</code>): a MAD z-score baseline, Isolation Forest, Local Outlier Factor and One-Class SVM, each at a 5% contamination assumption. Binary red flags are reported separately instead of being z-scored. What each detector is held to is checked live on the <kpilink>Model KPI page</kpilink>.`,
    step5: `Export the snapshot (<code>04</code>), descriptive tables (<code>05</code>), SHAP and permutation importance (<code>07</code>) and a live field dictionary (<code>08</code>).`,
  },
  band_h: "How the risk band is set",
  band_p: `A procedure is banded by how many detectors flagged it: <strong>medium</strong> = 1, <strong>high</strong> = 2, <strong>critical</strong> = 3 or more (consensus). Banding on agreement rather than on a score threshold keeps the bands comparable across models, whose raw score scales differ by orders of magnitude.`,
  band_note: `The percentile figure shown next to each band is the rank of the record's most extreme detector within this dataset. It is not a probability, and it is not comparable between different runs of the pipeline.`,
  absent_h: "Indicators that are deliberately absent",
  absent_p: `MTender does not publish these, so they are not computed and never shown as zero. An earlier version of this dashboard derived them from generated data, which made invented figures look like measurements.`,
  absent_th_field: "Field",
  absent_th_why: "Why it is unavailable",
  high_h: "What a high band means",
  high_p: `The detector flags statistical and rule-based irregularities used internationally as <em>corruption risk indicators</em>. It does not accuse a firm or a contracting authority. Moldova publishes no procedure-level "corrupt / not corrupt" label, so precision and recall are not computable on this source: model quality is evidenced by agreement between independent detectors and by univariate significance testing of each indicator against the consensus flag, while any evaluation against known labels requires an external dataset.`,
  high_p2: `Award amounts are summed across every awarded lot before being compared with the estimate, because <code>estimated_value</code> covers the whole procedure while a procedure can be awarded in hundreds of lots.`,
};

export default method;
