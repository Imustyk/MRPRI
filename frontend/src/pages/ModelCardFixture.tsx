import { useTranslation } from "react-i18next";
import { ModelWorkbench } from "../components/ModelExplanationCard";
import type { DetectorAnalysis, ModelAnalysis, Tender } from "../api";
import { PageHead } from "../ui";

/**
 * Dev-only fixture: renders the model card against *isolated* synthetic data so
 * the histogram states (score marker, hatched threshold marker, same-interval
 * coincidence, all-zero counts, missing score) can be verified visually even
 * when the served dataset carries no run provenance. Never reachable in a
 * production build: the route is registered behind `import.meta.env.DEV`.
 */

const bins = (selected: number | null, counts: number[] | "zero") =>
  counts === "zero"
    ? Array.from({ length: 8 }, (_, i) => ({
        index: i,
        start: i * 2,
        end: (i + 1) * 2,
        n: 0,
        selected: i === selected,
      }))
    : counts.map((n, i) => ({
        index: i,
        start: i * 2,
        end: (i + 1) * 2,
        n,
        selected: i === selected,
      }));

const detector = (over: Partial<DetectorAnalysis>): DetectorAnalysis => ({
  key: "statistical_mad_zscore",
  label: "MAD z-score",
  field: "mad_zscore",
  score: 11.2,
  verdict: "flagged",
  n_reference: 5000,
  n_missing_score: 40,
  score_percentile: 99.1,
  bins: bins(5, [900, 1100, 950, 700, 550, 420, 240, 140]),
  threshold: {
    value: 11,
    operator: ">",
    source: "results/mongo/detection_summary.json",
  },
  threshold_matches_verdict: true,
  params: { z_threshold: 11 },
  features: ["award_total_mdl", "n_bidders"],
  training_medians: null,
  training_mad: null,
  local_attribution: null,
  ...over,
});

const sameInterval = detector({});
const allZero = detector({
  key: "isolation_forest",
  label: "Isolation Forest",
  field: "if_score",
  score: 0.42,
  verdict: "flagged",
  bins: bins(null, "zero"),
  threshold: null,
  threshold_matches_verdict: null,
  params: { contamination: 0.01 },
});
const missingScore = detector({
  key: "local_outlier_factor",
  label: "Local Outlier Factor",
  field: "lof_score",
  score: null,
  verdict: "unavailable",
  score_percentile: null,
  bins: bins(null, [900, 1100, 950, 700, 550, 420, 240, 140]),
  threshold: { value: 5, operator: ">", source: "calibration fixture" },
  threshold_matches_verdict: null,
  params: { n_neighbors: 20 },
});

const context = (detectors: DetectorAnalysis[]): ModelAnalysis => ({
  tender_id: "fixture",
  run_id: "fixture-run-000",
  source: "isolated fixture (not production data)",
  summary_matches_run: true,
  generated_at: "2026-01-01T00:00:00Z",
  model_version: "fixture-1.0",
  n_reference: 5000,
  n_corpus: 152378,
  scope: "same_run_available_scores",
  detectors,
  agreement: detectors.map((l) =>
    detectors.map((r) => ({ left: l.key, right: r.key, n: 5000, n_agree: 4500, agreement: 0.9 })),
  ),
  consensus: { n_models_flagging: 2, flag: true, band: "high", percentile: 91 },
});

const tender = {
  tender_id: "fixture",
  risk_level: "high",
  n_models_flagging: 2,
  risk_score: 91.4,
  consensus_flag: true,
  model_flags: { statistical_mad_zscore: true, isolation_forest: true },
} as unknown as Tender;

export default function ModelCardFixture() {
  const { t } = useTranslation();
  return (
    <div data-fixture="model-card">
      <PageHead
        kicker="dev fixture"
        title={t("fixture.title")}
        lede={t("fixture.lede")}
      />
      <div className="callout warn">{t("fixture.notice")}</div>
      <ModelWorkbench tender={tender} analysis={context([sameInterval, allZero, missingScore])} />
    </div>
  );
}
