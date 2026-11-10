import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMeasure } from "../hooks";
import {
  buildQuartileLayout,
  classifyQuartileRow,
  quartileMarks,
  type QuartileRow,
  type ScaleRequest,
} from "../pages/quartileRange";

const LABEL_W = 176;
const PAD_RIGHT = 26;
const ROW_H = 30;
const AXIS_H = 34;
const TOP = 10;
/** Below this the labels would crush, so the box scrolls inside its container. */
const MIN_WIDTH = 440;
const FALLBACK_WIDTH = 720;

/**
 * Interquartile range per group: one span from the real p25 to the real p75 and
 * a separate diamond marker for the median.
 *
 * Deliberately not a stacked Bar chart: stacking would sum p25 + median + p75
 * into a length that matches no quartile. Nulls stay missing (the row becomes a
 * labelled placeholder instead of a bar from 0), and a log axis is only built
 * from strictly positive quartiles — rows it refuses are listed in the note
 * rendered by the caller rather than being dropped without a word.
 *
 * Rows are focusable, so mouse hover and keyboard focus both open the tooltip
 * with the raw quartiles, the measure's unit and n; the full raw table sits
 * below the chart.
 */
export function QuartileRangeChart({
  rows,
  scale,
  fmt,
  measureLabel,
  ariaId,
}: {
  rows: QuartileRow[];
  scale: ScaleRequest;
  /** Localised raw-value formatter (axis and tooltip). */
  fmt: (value: number) => string;
  /** Measure label incl. units, e.g. "Award total (MDL)". */
  measureLabel: string;
  ariaId?: string;
}) {
  const { t } = useTranslation();
  const measured = useMeasure<HTMLDivElement>();
  const [active, setActive] = useState<string | null>(null);

  const width = Math.max(measured.width || FALLBACK_WIDTH, MIN_WIDTH);
  const plotWidth = Math.max(80, width - LABEL_W - PAD_RIGHT);
  const layout = useMemo(
    () => buildQuartileLayout({ rows, requested: scale, plotWidth }),
    [rows, scale, plotWidth],
  );
  const height = TOP + rows.length * ROW_H + AXIS_H;
  const axisY = TOP + rows.length * ROW_H;

  const rowInfo = useMemo(
    () =>
      rows.map((row) => {
        const kind = classifyQuartileRow(row);
        const drawn = layout.drawn.some((item) => item.key === row.key);
        const excluded = layout.excluded.find((item) => item.key === row.key);
        const marks = drawn ? quartileMarks(row, layout) : null;
        return { row, kind, drawn, excluded, marks };
      }),
    [rows, layout],
  );

  const activeRow = rowInfo.find((info) => info.row.key === active) ?? null;

  const describeRow = (row: QuartileRow): string => {
    const kind = classifyQuartileRow(row);
    if (kind !== "valid") {
      return `${row.full}: ${t(kind === "missing" ? "distributions.spread_row_missing" : "distributions.spread_row_invalid", { n: row.n })}`;
    }
    return t("distributions.spread_row_summary", {
      name: row.full,
      measure: measureLabel,
      p25: fmt(row.p25 as number),
      median: row.median === null || !Number.isFinite(row.median) ? t("distributions.na") : fmt(row.median),
      p75: fmt(row.p75 as number),
      n: row.n,
    });
  };

  return (
    <div className="quartile-chart-wrap" ref={measured.ref}>
      <div className="quartile-scroll">
        <svg
          className="quartile-chart"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="group"
          aria-label={t("distributions.spread_chart_label", { measure: measureLabel })}
          id={ariaId}
        >
          {/* grid + ticks */}
          {layout.ticks.map((tick) => (
            <g key={`tick-${tick}`}>
              <line
                x1={LABEL_W + layout.toX(tick)}
                x2={LABEL_W + layout.toX(tick)}
                y1={TOP}
                y2={axisY}
                stroke="var(--line-soft)"
                strokeDasharray="2 4"
              />
              <text
                x={LABEL_W + layout.toX(tick)}
                y={axisY + 15}
                textAnchor="middle"
                fontSize={10}
                fill="var(--muted)"
              >
                {fmt(tick)}
              </text>
            </g>
          ))}
          <line
            x1={LABEL_W}
            x2={LABEL_W + plotWidth}
            y1={axisY}
            y2={axisY}
            stroke="var(--line)"
          />
          <text x={LABEL_W + plotWidth / 2} y={height - 3} textAnchor="middle" fontSize={11} fill="var(--muted)">
            {t("distributions.spread_value_axis", { measure: measureLabel })}
          </text>

          {rowInfo.map((info, index) => {
            const y = TOP + index * ROW_H;
            const midY = y + ROW_H / 2;
            const isActive = info.row.key === active;
            return (
              <g
                key={info.row.key}
                className={`quartile-row${isActive ? " active" : ""}`}
                tabIndex={0}
                role="img"
                aria-label={describeRow(info.row)}
                data-row={info.row.key}
                onMouseEnter={() => setActive(info.row.key)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(info.row.key)}
                onBlur={() => setActive(null)}
              >
                <rect
                  x={0}
                  y={y}
                  width={width}
                  height={ROW_H}
                  fill={isActive ? "var(--surface-secondary)" : "transparent"}
                />
                <text x={0} y={midY + 4} fontSize={11.5} fill="var(--ink)">
                  {info.row.name}
                </text>
                {info.marks ? (
                  <>
                    <rect
                      className="quartile-interval"
                      x={LABEL_W + Math.min(info.marks.x1, info.marks.x2)}
                      y={midY - 7}
                      width={Math.max(2, Math.abs(info.marks.x2 - info.marks.x1))}
                      height={14}
                      rx={4}
                      fill="var(--chart-range)"
                      stroke="var(--chart-blue)"
                      strokeWidth={1}
                    />
                    {info.marks.medianX !== null && (
                      <g className="quartile-median" data-median={info.row.key}>
                        <line
                          x1={LABEL_W + info.marks.medianX}
                          x2={LABEL_W + info.marks.medianX}
                          y1={midY - 11}
                          y2={midY + 11}
                          stroke="var(--chart-highlight)"
                          strokeWidth={2}
                        />
                        <rect
                          x={LABEL_W + info.marks.medianX - 3.5}
                          y={midY - 3.5}
                          width={7}
                          height={7}
                          transform={`rotate(45 ${LABEL_W + info.marks.medianX} ${midY})`}
                          fill="var(--chart-highlight)"
                        />
                      </g>
                    )}
                  </>
                ) : (
                  <text
                    className="quartile-placeholder"
                    x={LABEL_W + 4}
                    y={midY + 4}
                    fontSize={11}
                    fill="var(--muted)"
                  >
                    {info.excluded
                      ? t("distributions.spread_row_nonpos")
                      : t(
                          info.kind === "invalid"
                            ? "distributions.spread_row_invalid"
                            : "distributions.spread_row_missing",
                          { n: info.row.n },
                        )}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      {/* Reserved box below the chart: it never covers the data and never
          shifts the layout when it changes between rows. */}
      <div className="quartile-tip" data-tip-row={activeRow?.row.key ?? ""}>
        {!activeRow ? (
          <span className="muted">{t("distributions.spread_tip_hint")}</span>
        ) : (
          <>
            <strong>{activeRow.row.full}</strong>
            <div className="quartile-tip-sub">{measureLabel}</div>
            {classifyQuartileRow(activeRow.row) === "valid" ? (
              <div className="quartile-tip-row">
                <span>{t("distributions.th_p25")}</span>
                <span className="mono">{fmt(activeRow.row.p25 as number)}</span>
              </div>
            ) : null}
            {activeRow.row.median !== null && Number.isFinite(activeRow.row.median) ? (
              <div className="quartile-tip-row">
                <span>{t("distributions.th_median")}</span>
                <span className="mono">{fmt(activeRow.row.median)}</span>
              </div>
            ) : null}
            {classifyQuartileRow(activeRow.row) === "valid" ? (
              <div className="quartile-tip-row">
                <span>{t("distributions.th_p75")}</span>
                <span className="mono">{fmt(activeRow.row.p75 as number)}</span>
              </div>
            ) : null}
            <div className="quartile-tip-row">
              <span>{t("distributions.th_n")}</span>
              <span className="mono">{activeRow.row.n.toLocaleString()}</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
