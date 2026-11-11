import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { intlLocale } from "../i18n";
import { type DetectorAnalysis, type ModelAnalysis, type Tender } from "../api";
import { BandBadge, Empty, Pill, TableWrap } from "../ui";

export const MODEL_SHORT: Record<string, string> = { statistical_mad_zscore: "MAD", isolation_forest: "Isolation Forest", local_outlier_factor: "LOF", one_class_svm: "One-Class SVM" };
export function metric(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat(intlLocale(), { maximumFractionDigits: digits }).format(value);
}
export function Verdict({ value }: { value: DetectorAnalysis["verdict"] }) {
  const { t } = useTranslation();
  return <Pill tone={value === "flagged" ? "risk" : value === "not_flagged" ? "ok" : "muted"}>{t(`analysis.${value}`)}</Pill>;
}

/**
 * Everything the histogram needs to know before it draws: which intervals the
 * markers fall into, whether a marker may exist at all, and whether the counts
 * carry no information. Pure so the regression tests can assert the same-bin
 * case, the all-zero case and the missing-score case without a renderer.
 */
export function histogramFlags(model: DetectorAnalysis): {
  hasScore: boolean;
  hasBins: boolean;
  /** Index (bin.index) of the interval holding the selected score, or null. */
  selectedIndex: number | null;
  /** Index of the interval holding the stored boundary, or undefined. */
  thresholdBin: number | undefined;
  maxCount: number;
  allZero: boolean;
  sameInterval: boolean;
} {
  const hasScore = model.score !== null && Number.isFinite(model.score);
  const hasBins = model.bins.length > 0;
  // A score that is absent marks no interval: the marker is not drawn from a
  // stale `selected` flag, it is derived from a score that actually exists.
  const selectedIndex = hasScore ? model.bins.find((bin) => bin.selected)?.index ?? null : null;
  let thresholdBin: number | undefined;
  if (model.threshold) {
    const value = model.threshold.value;
    thresholdBin = model.bins.find((bin, index) =>
      value >= bin.start &&
      (value < bin.end || (index === model.bins.length - 1 && value <= bin.end)),
    )?.index;
  }
  const maxCount = Math.max(0, ...model.bins.map((bin) => bin.n));
  const allZero = hasBins && maxCount === 0;
  return {
    hasScore,
    hasBins,
    selectedIndex,
    thresholdBin,
    maxCount,
    allZero,
    sameInterval: selectedIndex !== null && thresholdBin === selectedIndex,
  };
}

/** Top-rounded bar path; zero-height bars render nothing at all. */
function barPath(x: number, y: number, w: number, h: number, r = 3): string | null {
  if (!(h > 0) || !(w > 0)) return null;
  const rr = Math.max(0, Math.min(r, w / 2, h));
  return [
    `M${x},${y + h}`,
    `L${x},${y + rr}`,
    `Q${x},${y} ${x + rr},${y}`,
    `L${x + w - rr},${y}`,
    `Q${x + w},${y} ${x + w},${y + rr}`,
    `L${x + w},${y + h}`,
    "Z",
  ].join(" ");
}

type HistogramBar = { index: number; start: number; end: number; n: number; display_n: number; label: string; selected: boolean };

export function ModelExplanationCard({ model, context }: { model: DetectorAnalysis; context: ModelAnalysis }) {
  const { t } = useTranslation();
  const [logCount, setLogCount] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const rawId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const hatchId = `hist-hatch-${rawId}`;
  const flags = histogramFlags(model);
  const useLog = logCount && !flags.allZero;
  const bars: HistogramBar[] = model.bins.map((bin) => ({
    ...bin,
    label: `${metric(bin.start)} – ${metric(bin.end)}`,
    // log10(1 + count): counts of zero stay at zero instead of −∞.
    display_n: useLog ? Math.log10(1 + bin.n) : bin.n,
  }));
  const selected = flags.selectedIndex === null ? undefined : model.bins.find((bin) => bin.index === flags.selectedIndex);
  // Recharts types a custom shape as (props: unknown) => Element, so the
  // narrow props are read defensively and "nothing to draw" is an empty <g>.
  const renderBar = (raw: unknown): JSX.Element => {
    const { x = 0, y = 0, width = 0, height = 0, payload } = (raw ?? {}) as {
      x?: number; y?: number; width?: number; height?: number; payload?: HistogramBar;
    };
    if (!payload) return <g />;
    const d = barPath(x, y, width, height);
    if (d === null) return <g />;
    const isSelected = flags.selectedIndex !== null && payload.index === flags.selectedIndex;
    const isThreshold = flags.thresholdBin !== undefined && payload.index === flags.thresholdBin;
    return (
      <g className={`hist-bar${isSelected ? " hist-bar-selected" : ""}${isThreshold ? " hist-bar-threshold" : ""}`} data-bin={payload.index}>
        <path d={d} fill={isSelected ? "var(--chart-highlight)" : "var(--chart-blue)"} />
        {/* Texture, not only hue: the threshold interval reads as hatched even
            when it is also the selected one. */}
        {isThreshold && <path d={d} fill={`url(#${hatchId})`} />}
      </g>
    );
  };

  return (
    <article className="model-explanation surface" data-model={model.key}>
      <header className="section-heading"><div><span className="eyebrow">{t("analysis.model_explanation")}</span><h3>{model.label}</h3></div><Verdict value={model.verdict} /></header>
      <p className="muted">{t(`analysis.models.${model.key}.description`)}</p>
      <div className="model-metrics">
        <div><span>{t("analysis.raw_score")}</span><strong>{metric(model.score, 6)}</strong><small><code>{model.field}</code></small></div>
        <div><span>{t("analysis.score_rank")}</span><strong>{model.score_percentile === null ? "—" : `${metric(model.score_percentile, 1)} / 100`}</strong><small>{t("analysis.rank_definition")}</small></div>
        <div><span>{t("analysis.reference_size")}</span><strong>{metric(model.n_reference, 0)}</strong><small>{t("analysis.same_run")}</small></div>
      </div>
      {flags.hasBins ? <>
        <div className="chart-heading"><h4>{t("analysis.score_distribution")}</h4><label className="compact-toggle"><input type="checkbox" checked={logCount} onChange={(event) => setLogCount(event.target.checked)} />{t("analysis.log_counts")}</label></div>
        <p className="microcopy">{t("analysis.hist_scope", { n: metric(model.n_reference, 0), missing: metric(model.n_missing_score, 0), run: context.run_id ?? "—" })}</p>
        <div className="score-histogram" role="img" aria-label={t("analysis.hist_a11y", { name: model.label, value: metric(model.score, 6) })}>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={bars} margin={{ top: 20, right: 16, bottom: 24, left: 12 }}>
              <defs>
                <pattern id={hatchId} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                  <line x1="0" y1="0" x2="0" y2="7" stroke="var(--red)" strokeWidth="2.4" />
                </pattern>
              </defs>
              <CartesianGrid stroke="var(--line-soft)" vertical={false} />
              <XAxis dataKey="index" tickFormatter={(index: number) => {
                const start = bars.find(bin => bin.index === index)?.start;
                return start !== undefined && Math.abs(start) >= 1_000_000 ? start.toExponential(1) : metric(start);
              }} minTickGap={28} tick={{ fill: "var(--muted)", fontSize: 10 }} label={{ value: t("analysis.score_intervals"), position: "insideBottom", offset: -16, fill: "var(--muted)", fontSize: 11 }} />
              <YAxis width={58} allowDecimals={false} tick={{ fill: "var(--muted)", fontSize: 10 }} tickFormatter={(value: number) => metric(useLog ? Math.round(10 ** value - 1) : value, 0)} domain={[0, useLog ? Math.log10(1 + flags.maxCount) : flags.allZero ? 1 : "auto"]} ticks={flags.allZero ? [0] : undefined} />
              <Tooltip allowEscapeViewBox={{ x: false, y: false }} position={{ y: 0 }} labelFormatter={(index) => bars.find(bin => bin.index === Number(index))?.label ?? String(index)} formatter={(_value, _name, item) => [metric(item.payload.n, 0), t("analysis.procedures")]} />
              <Bar dataKey="display_n" isAnimationActive={false} shape={renderBar} />
              {/* Threshold first: at a shared interval its dashed 5px line sits
                  behind the solid 2px score line, both stay legible. */}
              {flags.thresholdBin !== undefined && <ReferenceLine x={flags.thresholdBin} stroke="var(--red)" strokeWidth={5} strokeDasharray="6 5" />}
              {selected && <ReferenceLine x={selected.index} stroke="var(--chart-highlight)" strokeWidth={2} />}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <ul className="legend">
          <li><i className="legend-marker selected" />{flags.hasScore ? t("analysis.legend_selected", { v: metric(model.score, 6) }) : t("analysis.selected_interval")}</li>
          {flags.thresholdBin !== undefined && model.threshold && <li><i className="legend-marker threshold" />{t("analysis.legend_threshold", { v: `${model.threshold.operator} ${metric(model.threshold.value, 6)}` })}</li>}
          {flags.sameInterval && <li className="muted">{t("analysis.same_interval")}</li>}
          <li>{useLog ? t("analysis.y_log") : t("analysis.y_count")}</li>
        </ul>
        {useLog && <p className="microcopy">{t("analysis.log_note_raw")}</p>}
        {flags.allZero && <p className="microcopy">{t("analysis.hist_all_zero")}</p>}
        <p className="microcopy">{t("analysis.bin_note")}</p>
      </> : <Empty title={t("analysis.reference_unavailable")} hint={t("analysis.reference_reason")} />}
      <div className="model-boundary"><strong>{t("analysis.threshold")}</strong><span>{model.threshold ? `${model.threshold.operator} ${metric(model.threshold.value, 6)}` : t("analysis.unavailable")}</span></div>
      {model.threshold && <p className="microcopy break-anywhere">{t("analysis.source")}: <code>{model.threshold.source}</code></p>}
      {model.threshold_matches_verdict === false && <p className="callout warn">{t("analysis.threshold_mismatch")}</p>}
      <p className="microcopy">{t(`analysis.models.${model.key}.limitation`)}</p>
      <details className="research-disclosure"><summary>{t("analysis.features_parameters")}</summary>
        <h4>{t("analysis.features")}</h4>{model.key === "statistical_mad_zscore" && <code className="formula">maxⱼ |xⱼ − medianⱼ| / (1.4826 × MADⱼ)</code>}{model.features.length ? <ul className="feature-chips">{model.features.map((feature) => <li key={feature}><code>{feature}</code></li>)}</ul> : <p>{t("analysis.unavailable")}</p>}
        <h4>{t("analysis.parameters")}</h4><dl className="kv">{Object.entries(model.params).filter(([, value]) => !Array.isArray(value)).map(([key, value]) => <div className="kv-pair" key={key}><dt><code>{key}</code></dt><dd>{String(value)}</dd></div>)}</dl>
        <p className="microcopy">{t("analysis.no_attribution")}</p>
      </details>
      <details className="research-disclosure" open={showAll} onToggle={(event) => setShowAll(event.currentTarget.open)}><summary>{t("analysis.distribution_table")}</summary>
        <TableWrap><table><thead><tr><th scope="col">{t("analysis.score_intervals")}</th><th scope="col">{t("analysis.procedures")}</th><th scope="col">{t("analysis.selection")}</th></tr></thead><tbody>{model.bins.map((bin) => <tr key={bin.index} className={bin.index === flags.thresholdBin ? "threshold-row" : undefined}><th scope="row">{metric(bin.start, 6)} – {metric(bin.end, 6)}</th><td>{metric(bin.n, 0)}</td><td>{bin.selected && flags.hasScore ? t("analysis.selected_interval") : "—"}{bin.index === flags.thresholdBin && <div className="muted">{t("analysis.threshold_interval")}</div>}</td></tr>)}</tbody></table></TableWrap>
      </details>
      <footer className="model-source"><span>{t("analysis.source")}: {context.source ?? t("analysis.unavailable")}</span><span>{t("analysis.run")}: <code>{context.run_id ?? "—"}</code></span><span>{t("analysis.version")}: {context.model_version ?? t("analysis.unavailable")}</span></footer>
    </article>
  );
}

export function ModelWorkbench({ tender, analysis }: { tender: Tender; analysis: ModelAnalysis }) {
  const { t } = useTranslation();
  const [active, setActive] = useState(analysis.detectors[0]?.key);
  const model = analysis.detectors.find((item) => item.key === active) ?? analysis.detectors[0];
  const id = useId();
  const count = analysis.detectors.length;
  return <section className="model-workbench" aria-labelledby={`${id}-title`}>
    <div className="section-heading"><div><span className="eyebrow">{t("analysis.explainability_first")}</span><h2 id={`${id}-title`}>{t("analysis.compare_models")}</h2></div><BandBadge level={tender.risk_level} nModels={tender.n_models_flagging} /></div>
    <div className="consensus-summary surface">
      <div><span>{t("analysis.votes")}</span><strong>{tender.n_models_flagging == null ? "—" : `${tender.n_models_flagging} / 4`}</strong></div>
      <div><span>{t("analysis.relative_rank")}</span><strong>{metric(tender.risk_score, 1)}{tender.risk_score != null ? " / 100" : ""}</strong></div>
      <div><span>{t("analysis.consensus")}</span><strong>{tender.consensus_flag == null ? t("analysis.unavailable") : tender.consensus_flag ? t("analysis.yes") : t("analysis.no")}</strong></div>
      <p>{t("analysis.coverage_decisions")}: {Object.values(tender.model_flags ?? {}).filter((value) => typeof value === "boolean").length} / 4. {t("analysis.voting_note")}</p>
    </div>
    {!analysis.summary_matches_run && <p className="callout warn">{t("analysis.run_unverified")}</p>}
    <TableWrap><table className="model-vote-table"><caption>{t("analysis.scales_note")}</caption><thead><tr><th scope="col">{t("analysis.model")}</th><th scope="col">{t("analysis.raw_score")}</th><th scope="col">{t("analysis.verdict")}</th><th scope="col">{t("analysis.details")}</th></tr></thead><tbody>{analysis.detectors.map((item) => <tr key={item.key} className={item.key === model?.key ? "selected-row" : ""}><th scope="row">{item.label}</th><td className="mono">{metric(item.score, 6)}</td><td><Verdict value={item.verdict} /></td><td><button className="ghost small" onClick={() => {
      setActive(item.key);
      requestAnimationFrame(() => {
        const panel = document.getElementById(`${id}-panel`);
        panel?.focus({ preventScroll: true });
        panel?.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      });
    }} aria-pressed={item.key === model?.key}>{t("analysis.inspect")}</button></td></tr>)}</tbody></table></TableWrap>
    {/* Tab list follows the detector count actually present: 0 detectors render
        no tabs at all, and arrows/Home/End wrap within that count. */}
    {count > 0 && <div className="model-tabs" role="tablist" aria-label={t("analysis.compare_models")}>
      {analysis.detectors.map((item, index) => <button key={item.key} id={`${id}-${item.key}`} role="tab" aria-controls={`${id}-panel`} aria-selected={item.key === model?.key} tabIndex={item.key === model?.key ? 0 : -1} onClick={() => setActive(item.key)} onKeyDown={(event) => {
        const next = event.key === "ArrowRight" ? (index + 1) % count
          : event.key === "ArrowLeft" ? (index - 1 + count) % count
          : event.key === "Home" ? 0
          : event.key === "End" ? count - 1 : -1;
        if (next < 0 || next >= count) return;
        const target = analysis.detectors[next];
        if (!target) return;
        event.preventDefault();
        setActive(target.key);
        document.getElementById(`${id}-${target.key}`)?.focus();
      }}>{MODEL_SHORT[item.key] ?? item.label}</button>)}
    </div>}
    {model && <div id={`${id}-panel`} role="tabpanel" tabIndex={0} aria-labelledby={`${id}-${model.key}`}><ModelExplanationCard key={model.key} model={model} context={analysis} /></div>}
    {count > 0 && <details className="surface research-disclosure agreement-panel"><summary>{t("analysis.agreement_title")}</summary><p className="microcopy">{t("analysis.agreement_scope", { n: metric(analysis.n_reference, 0), run: analysis.run_id ?? "—" })}</p>
      <TableWrap><table className="agreement-table"><caption>{t("analysis.agreement_definition")}</caption><thead><tr><th scope="col">{t("analysis.model")}</th>{analysis.detectors.map((item) => <th scope="col" key={item.key}>{MODEL_SHORT[item.key] ?? item.label}</th>)}</tr></thead><tbody>{analysis.agreement.map((cells, i) => {
        // A partial agreement matrix must not index past the detector list.
        const rowModel = analysis.detectors[i];
        if (!rowModel) return null;
        return <tr key={rowModel.key}><th scope="row">{MODEL_SHORT[rowModel.key] ?? rowModel.label}</th>{cells.map((cell) => <td key={cell.right} style={{ background: cell.agreement === null ? undefined : `color-mix(in srgb, var(--chart-blue) ${Math.round(cell.agreement * 18)}%, var(--card))` }}>{cell.agreement === null ? "—" : `${metric(100 * cell.agreement, 1)}%`}<small>{metric(cell.n_agree, 0)} / {metric(cell.n, 0)}</small></td>)}</tr>;
      })}</tbody></table></TableWrap>
    </details>}
  </section>;
}
