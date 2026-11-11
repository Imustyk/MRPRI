import { describe, expect, it } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { histogramFlags, ModelWorkbench } from "./ModelExplanationCard";
import type { DetectorAnalysis, ModelAnalysis, Tender } from "../api";

function detector(over: Partial<DetectorAnalysis> = {}): DetectorAnalysis {
  return {
    key: "statistical_mad_zscore",
    label: "MAD z-score",
    field: "score",
    score: 5,
    verdict: "flagged",
    n_reference: 1000,
    n_missing_score: 10,
    score_percentile: 97.2,
    bins: [
      { index: 0, start: 0, end: 10, n: 900, selected: true },
      { index: 1, start: 10, end: 20, n: 90, selected: false },
      { index: 2, start: 20, end: 30, n: 10, selected: false },
    ],
    threshold: { value: 7.5, operator: ">", source: "isolation_forest.contamination" },
    threshold_matches_verdict: true,
    params: {},
    features: ["award_total_mdl"],
    training_medians: null,
    training_mad: null,
    local_attribution: null,
    ...over,
  };
}

function analysis(detectors: DetectorAnalysis[]): ModelAnalysis {
  return {
    tender_id: "t1",
    run_id: "run-1",
    source: "notebooks/eval",
    summary_matches_run: true,
    generated_at: null,
    model_version: "1.0",
    n_reference: 1000,
    n_corpus: 152378,
    scope: "same_run_available_scores",
    detectors,
    agreement: detectors.map((l) =>
      detectors.map((r) => ({ left: l.key, right: r.key, n: 1000, n_agree: 900, agreement: 0.9 })),
    ),
    consensus: { n_models_flagging: 1, flag: true, band: "medium", percentile: 77 },
  };
}

const tender = {
  tender_id: "t1",
  risk_level: "medium",
  n_models_flagging: 1,
  risk_score: 77.3,
  consensus_flag: true,
  model_flags: { statistical_mad_zscore: true },
} as unknown as Tender;

describe("histogramFlags", () => {
  it("detects the score and boundary sharing one interval", () => {
    const flags = histogramFlags(detector());
    expect(flags.hasScore).toBe(true);
    expect(flags.selectedIndex).toBe(0); // score 5 ∈ [0, 10)
    expect(flags.thresholdBin).toBe(0); // 7.5 ∈ [0, 10)
    expect(flags.sameInterval).toBe(true);
  });

  it("keeps the boundary interval separate when they differ", () => {
    const flags = histogramFlags(detector({ threshold: { value: 15, operator: ">", source: "x" } }));
    expect(flags.selectedIndex).toBe(0);
    expect(flags.thresholdBin).toBe(1);
    expect(flags.sameInterval).toBe(false);
  });

  it("places a boundary exactly on a bin edge into the next interval", () => {
    const flags = histogramFlags(detector({ threshold: { value: 10, operator: ">=", source: "x" } }));
    expect(flags.thresholdBin).toBe(1);
  });

  it("draws no score marker when the score is missing, even if a bin is flagged", () => {
    const flags = histogramFlags(detector({ score: null }));
    expect(flags.hasScore).toBe(false);
    expect(flags.selectedIndex).toBeNull();
    expect(flags.sameInterval).toBe(false);
  });

  it("recognises an all-zero histogram", () => {
    const flags = histogramFlags(
      detector({
        bins: [
          { index: 0, start: 0, end: 10, n: 0, selected: true },
          { index: 1, start: 10, end: 20, n: 0, selected: false },
        ],
      }),
    );
    expect(flags.allZero).toBe(true);
    expect(flags.maxCount).toBe(0);
  });

  it("reports an absent histogram without inventing markers", () => {
    const flags = histogramFlags(detector({ bins: [], score: 3, threshold: null }));
    expect(flags.hasBins).toBe(false);
    expect(flags.thresholdBin).toBeUndefined();
    expect(flags.selectedIndex).toBeNull();
  });
});

describe("ModelWorkbench keyboard navigation", () => {
  const keys = ["statistical_mad_zscore", "isolation_forest", "local_outlier_factor", "one_class_svm"] as const;

  it("renders no tablist when there are no detectors", () => {
    render(<ModelWorkbench tender={tender} analysis={analysis([])} />);
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("tolerates a single detector: arrows never wrap into nothing", () => {
    const single = detector();
    render(<ModelWorkbench tender={tender} analysis={analysis([single])} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(1);
    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(document.activeElement).toBe(tabs[0]);
    fireEvent.keyDown(tabs[0], { key: "End" });
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
  });

  it("wraps arrows and honours Home/End for four detectors", () => {
    const detectors = keys.map((key, i) => detector({ key, label: `m${i}` }));
    render(<ModelWorkbench tender={tender} analysis={analysis(detectors)} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(4);

    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1].getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tabs[1]);

    fireEvent.keyDown(tabs[1], { key: "ArrowLeft" });
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    // Left from the first tab wraps to the last one (count-based, not % 4).
    fireEvent.keyDown(tabs[0], { key: "ArrowLeft" });
    expect(tabs[3].getAttribute("aria-selected")).toBe("true");

    fireEvent.keyDown(tabs[3], { key: "Home" });
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(tabs[0], { key: "End" });
    expect(tabs[3].getAttribute("aria-selected")).toBe("true");
  });

  it("hides agreement with no comparable decisions", () => {
    const model = analysis([detector(), detector({ key: "isolation_forest" })]);
    model.agreement = model.agreement.map(row => row.map(cell => ({ ...cell, n: 0, n_agree: 0, agreement: null })));
    const { container } = render(<ModelWorkbench tender={tender} analysis={model} />);
    expect(container.querySelector(".agreement-panel")).toBeNull();
  });

  it("shows each available pair once and keeps a real zero percent", () => {
    const model = analysis([detector(), detector({ key: "isolation_forest" }), detector({ key: "local_outlier_factor" })]);
    model.agreement = model.agreement.map(row => row.map(cell => cell.left === "local_outlier_factor" || cell.right === "local_outlier_factor"
      ? { ...cell, n: 0, n_agree: 0, agreement: null }
      : { ...cell, n: 10, n_agree: 0, agreement: 0 }));
    const { container } = render(<ModelWorkbench tender={tender} analysis={model} />);
    expect(container.querySelectorAll(".agreement-table tbody tr")).toHaveLength(1);
    expect(container.querySelector(".agreement-table tbody")?.textContent).toContain("0 / 10");
  });
});
