/**
 * Geometry of the "spread by group" chart (interval p25 → p75 with a separate
 * median marker).
 *
 * Pure functions with no React and no rendering concerns, so the regression
 * tests can assert *numeric* geometry: the interval is a span from p25 to p75
 * (never a sum of three stacked bars), null quartiles stay missing, and a
 * logarithmic axis is only built from strictly positive values — anything the
 * log scale refuses is reported with the offending groups instead of being
 * silently dropped or coerced to zero.
 */

export type QuartileRow = {
  key: string;
  /** Short label for the axis. */
  name: string;
  /** Full label for tooltips, tables and announcements. */
  full: string;
  p25: number | null;
  median: number | null;
  p75: number | null;
  n: number;
};

export type RowKind = "valid" | "missing" | "invalid";

export type ScaleRequest = "auto" | "log" | "linear";

/** Why a row cannot be drawn at all (placeholders, not scale exclusions). */
export type RowProblem = "missing" | "invalid";

export type ExcludedRow = {
  key: string;
  name: string;
  reason: "non_positive" | RowProblem;
};

export type QuartileLayout = {
  used: "linear" | "log";
  requested: ScaleRequest;
  /** True when a log axis was asked for but nothing positive was left to place. */
  logRefused: boolean;
  /** Rows drawn on the axis (valid; log keeps only strictly positive ones). */
  drawn: QuartileRow[];
  /** Rows omitted from a log axis because a quartile is zero, negative or absent. */
  excluded: ExcludedRow[];
  /** Rows without a drawable interval at all — rendered as labelled placeholders. */
  undrawable: { key: string; name: string; reason: RowProblem }[];
  min: number;
  max: number;
  /** Absolute x inside the plot area for a value (0 … plotWidth). */
  toX: (value: number) => number;
  ticks: number[];
  plotWidth: number;
};

const finite = (v: number | null): v is number => v !== null && Number.isFinite(v);

/** p25/p75 decide the bar; a row is only usable when the span is not inverted. */
export function classifyQuartileRow(row: QuartileRow): RowKind {
  if (!finite(row.p25) || !finite(row.p75)) return "missing";
  if (row.p25 > row.p75) return "invalid";
  return "valid";
}

/** Every finite endpoint of a valid row, for the axis domain. */
function endpoints(rows: QuartileRow[]): number[] {
  const out: number[] = [];
  for (const row of rows) {
    if (finite(row.p25)) out.push(row.p25);
    if (finite(row.median)) out.push(row.median);
    if (finite(row.p75)) out.push(row.p75);
  }
  return out;
}

/** Log is admissible only when every endpoint that will be placed is > 0. */
function rowPositive(row: QuartileRow): boolean {
  return (
    (!finite(row.p25) || row.p25 > 0) &&
    (!finite(row.median) || row.median > 0) &&
    (!finite(row.p75) || row.p75 > 0)
  );
}

/** Drawn rows a log axis must refuse — reported to the user instead of dropped. */
export function nonPositiveQuartileRows(rows: QuartileRow[]): QuartileRow[] {
  return rows.filter((row) => classifyQuartileRow(row) === "valid" && !rowPositive(row));
}

function linearTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min > max) return [];
  if (min === max) return [min];
  const raw = (max - min) / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) {
    out.push(Number(v.toFixed(12)));
  }
  return out;
}

function logTicks(min: number, max: number): number[] {
  if (!(min > 0) || !(max > 0)) return [];
  const lo = Math.floor(Math.log10(min));
  const hi = Math.ceil(Math.log10(max));
  const decades = hi - lo;
  const stride = Math.max(1, Math.ceil((decades + 1) / 7));
  const out: number[] = [];
  for (let e = lo; e <= hi; e += stride) out.push(10 ** e);
  if (out.length === 0) out.push(min, max);
  return out;
}

/** Domain + mapping for one axis. Shared by the renderer and the tests. */
export function buildQuartileLayout({
  rows,
  requested = "auto",
  plotWidth,
  /** Span (max/min) that makes "auto" reach for a log axis. */
  autoLogSpan = 100,
}: {
  rows: QuartileRow[];
  requested?: ScaleRequest;
  plotWidth: number;
  autoLogSpan?: number;
}): QuartileLayout {
  const valid: QuartileRow[] = [];
  const undrawable: QuartileLayout["undrawable"] = [];
  for (const row of rows) {
    const kind = classifyQuartileRow(row);
    if (kind === "valid") valid.push(row);
    else undrawable.push({ key: row.key, name: row.full, reason: kind });
  }

  const values = endpoints(valid);
  const min0 = values.length ? Math.min(...values) : 0;
  const max0 = values.length ? Math.max(...values) : 1;
  const allPositive = valid.length > 0 && valid.every(rowPositive);
  const span = min0 > 0 && max0 > 0 ? max0 / min0 : Infinity;

  let used: "linear" | "log" = "linear";
  if (requested === "log") used = "log";
  else if (requested === "auto" && allPositive && span >= autoLogSpan) used = "log";

  let drawn = valid;
  let excluded: ExcludedRow[] = [];
  if (used === "log") {
    if (!allPositive) {
      const positive = valid.filter(rowPositive);
      if (positive.length === 0) {
        // Nothing positive to place: fall back rather than render an empty
        // logarithmic axis, and say so.
        used = "linear";
        drawn = valid;
      } else {
        drawn = positive;
        excluded = valid
          .filter((row) => !rowPositive(row))
          .map((row) => ({ key: row.key, name: row.full, reason: "non_positive" as const }));
      }
    }
  }

  const values2 = endpoints(drawn);
  let min = values2.length ? Math.min(...values2) : 0;
  let max = values2.length ? Math.max(...values2) : 1;
  if (used === "linear") {
    if (min === max) {
      // A single value still needs a readable axis around it.
      if (max === 0) {
        min = -0.5;
        max = 0.5;
      } else {
        const pad = Math.abs(max) * 0.1;
        min -= pad;
        max += pad;
      }
    }
  } else if (min === max) {
    min /= 10;
    max *= 10;
  }

  const width = Math.max(1, plotWidth);
  const toX =
    used === "log"
      ? (value: number) => {
          if (!(value > 0)) return 0;
          const lo = Math.log10(min);
          const hi = Math.log10(max);
          if (hi === lo) return width / 2;
          return ((Math.log10(value) - lo) / (hi - lo)) * width;
        }
      : (value: number) => {
          if (max === min) return width / 2;
          return ((value - min) / (max - min)) * width;
        };

  return {
    used,
    requested,
    logRefused: requested === "log" && used === "linear",
    drawn,
    excluded,
    undrawable,
    min,
    max,
    toX,
    ticks: used === "log" ? logTicks(min, max) : linearTicks(min, max),
    plotWidth: width,
  };
}

/**
 * The three values are laid out individually — the caller never stacks them.
 * Kept as an explicit helper so a test can prove that 10/20/30 becomes an
 * interval of exactly x(30) − x(10) with the median at x(20), not a stacked
 * total of 60.
 */
export function quartileMarks(
  row: QuartileRow,
  layout: QuartileLayout,
): { x1: number; x2: number; medianX: number | null } | null {
  if (!finite(row.p25) || !finite(row.p75)) return null;
  if (row.p25 > row.p75) return null;
  if (layout.used === "log" && !(row.p25 > 0)) return null;
  return {
    x1: layout.toX(row.p25),
    x2: layout.toX(row.p75),
    medianX: finite(row.median) ? layout.toX(row.median) : null,
  };
}
