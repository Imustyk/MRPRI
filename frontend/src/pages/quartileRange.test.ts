import { describe, expect, it } from "vitest";
import {
  buildQuartileLayout,
  classifyQuartileRow,
  nonPositiveQuartileRows,
  quartileMarks,
  type QuartileRow,
} from "./quartileRange";

const row = (over: Partial<QuartileRow>): QuartileRow => ({
  key: over.key ?? "g",
  name: over.name ?? "group",
  full: over.full ?? "group full",
  p25: 10,
  median: 20,
  p75: 30,
  n: 100,
  ...over,
});

describe("quartile geometry", () => {
  it("draws p25 → p75 as an interval with a separate median, never a sum", () => {
    const layout = buildQuartileLayout({
      rows: [row({ key: "a" })],
      requested: "linear",
      plotWidth: 200,
    });
    const marks = quartileMarks(row({ key: "a" }), layout)!;
    // Domain is exactly 10..30 over 200px: p25 at 0, p75 at 200, median at 100.
    expect(marks.x1).toBeCloseTo(0, 6);
    expect(marks.x2).toBeCloseTo(200, 6);
    expect(marks.medianX).toBeCloseTo(100, 6);
    // The span is the interval width (200px), not a stacked 10+20+30 total:
    // stacking would place the end far beyond x(30).
    expect(marks.x2 - marks.x1).toBeCloseTo(layout.toX(30) - layout.toX(10), 6);
    expect(marks.x2 - marks.x1).toBeLessThan(layout.toX(60) - layout.toX(10));
    // The median sits strictly inside the interval.
    expect(marks.medianX).toBeGreaterThan(marks.x1);
    expect(marks.medianX).toBeLessThan(marks.x2);
  });

  it("keeps a null quartile missing instead of drawing from zero", () => {
    const missing = row({ p25: null });
    expect(classifyQuartileRow(missing)).toBe("missing");
    const layout = buildQuartileLayout({ rows: [missing], plotWidth: 200 });
    expect(layout.drawn).toHaveLength(0);
    expect(layout.undrawable).toEqual([{ key: "g", name: "group full", reason: "missing" }]);
    expect(quartileMarks(missing, layout)).toBeNull();
  });

  it("marks an inverted interval (p25 > p75) as invalid, not drawable", () => {
    const inverted = row({ p25: 50, p75: 20 });
    expect(classifyQuartileRow(inverted)).toBe("invalid");
    const layout = buildQuartileLayout({ rows: [inverted], plotWidth: 200 });
    expect(layout.drawn).toHaveLength(0);
    expect(layout.undrawable[0]?.reason).toBe("invalid");
    expect(quartileMarks(inverted, layout)).toBeNull();
  });

  it("handles zero and negative quartiles on a linear axis", () => {
    const rows = [row({ key: "z", p25: 0, median: 5, p75: 10 }), row({ key: "neg", p25: -100, median: -50, p75: -10 })];
    const layout = buildQuartileLayout({ rows, requested: "auto", plotWidth: 300 });
    expect(layout.used).toBe("linear");
    expect(layout.drawn).toHaveLength(2);
    // Domain spans -100..10: zero is inside the axis, negatives left of it.
    expect(layout.toX(-100)).toBeCloseTo(0, 6);
    expect(layout.toX(10)).toBeCloseTo(300, 6);
    expect(layout.toX(-10)).toBeLessThan(layout.toX(0));
    expect(layout.toX(0)).toBeLessThan(layout.toX(5));
    expect(layout.min).toBe(-100);
    expect(layout.max).toBe(10);
  });

  it("refuses to put non-positive rows on an explicit log axis and names them", () => {
    const rows = [row({ key: "zero", p25: 0, median: 5, p75: 10 }), row({ key: "ok", p25: 100, median: 500, p75: 1000 })];
    const layout = buildQuartileLayout({ rows, requested: "log", plotWidth: 300 });
    expect(layout.used).toBe("log");
    expect(layout.drawn.map((r) => r.key)).toEqual(["ok"]);
    expect(layout.excluded).toEqual([{ key: "zero", name: "group full", reason: "non_positive" }]);
    expect(nonPositiveQuartileRows(rows).map((r) => r.key)).toEqual(["zero"]);
  });

  it("falls back to a linear axis when a requested log scale has nothing positive", () => {
    const rows = [row({ key: "neg", p25: -10, median: -5, p75: -1 })];
    const layout = buildQuartileLayout({ rows, requested: "log", plotWidth: 300 });
    expect(layout.used).toBe("linear");
    expect(layout.logRefused).toBe(true);
    expect(layout.drawn).toHaveLength(1);
    expect(layout.excluded).toHaveLength(0);
  });

  it("auto-selects log only for positive values spanning ≥ 100×", () => {
    const wide = [
      row({ key: "a", p25: 1, median: 10, p75: 100 }),
      row({ key: "b", p25: 10, median: 1000, p75: 10000 }),
    ];
    const layout = buildQuartileLayout({ rows: wide, requested: "auto", plotWidth: 200 });
    expect(layout.used).toBe("log");
    expect(layout.toX(1)).toBeCloseTo(0, 6);
    expect(layout.toX(10000)).toBeCloseTo(200, 6);
    expect(layout.ticks).toContain(100);
    // A narrow positive span stays linear.
    const narrow = buildQuartileLayout({ rows: [row({ p25: 1, median: 2, p75: 3 })], plotWidth: 200 });
    expect(narrow.used).toBe("linear");
    // A wide span that includes zero cannot be logged.
    const withZero = buildQuartileLayout({
      rows: [row({ p25: 0, median: 1, p75: 10000 }), row({ key: "b", p25: 100, median: 500, p75: 100000 })],
      plotWidth: 200,
    });
    expect(withZero.used).toBe("linear");
  });

  it("produces no drawable marks for non-positive endpoints on a log axis", () => {
    const layout = buildQuartileLayout({
      rows: [row({ key: "ok", p25: 100, median: 500, p75: 1000 })],
      requested: "log",
      plotWidth: 200,
    });
    expect(quartileMarks(row({ p25: 0, median: 5, p75: 10 }), layout)).toBeNull();
    expect(quartileMarks(row({ p25: -1, median: 5, p75: 10 }), layout)).toBeNull();
  });
});
