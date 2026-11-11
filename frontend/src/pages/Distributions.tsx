import { Fragment, useMemo, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import i18n from "../i18n";
import { tr } from "../i18n/backendMap";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import {
  RISK_COLOR,
  getCorrelations,
  getCrosstab,
  getDistribution,
  getFeatures,
  getGroupCompare,
  getScatter,
  int,
  num,
  num1,
  pct,
  val,
  type CategoryMeta,
  type Correlations,
  type Crosstab,
  type Distribution,
  type FeatureCatalog,
  type GroupCompare,
  type RiskLevel,
  type ScatterData,
} from "../api";
import { useRequest } from "../hooks";
import {
  Empty,
  ErrorNote,
  Field,
  MiniStats,
  PageHead,
  Panel,
  RequestPanel,
  Skeleton,
  Tabs,
  TableWrap,
  corrColor,
} from "../ui";
import { QuartileRangeChart } from "../components/QuartileRangeChart";
import {
  buildQuartileLayout,
  classifyQuartileRow,
  nonPositiveQuartileRows,
  type QuartileRow,
  type ScaleRequest,
} from "./quartileRange";

type TabKey = "corr" | "dist" | "rel" | "mix";

const RISK_KEYS = new Set(["unscored", "low", "medium", "high", "critical"]);

/** Localise a backend feature/category/group label, including risk-band keys. */
function labelOf(s: string): string {
  if (s === "(none)") return i18n.t("distributions.none_group");
  if (RISK_KEYS.has(s)) return i18n.t(`risk.${s}`);
  return tr(s);
}

/**
 * Big or small numbers should not silently become "0" in a chart axis, and a
 * missing quartile must stay missing — it renders as "—", never as zero.
 */
function axisFmt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return i18n.t("common.empty_value");
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}${i18n.t("distributions.axis_bn")}`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}${i18n.t("distributions.axis_m")}`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}${i18n.t("distributions.axis_k")}`;
  if (a < 0.01) return v.toExponential(0);
  return String(Math.round(v * 100) / 100);
}

const GROUP_FALLBACK = "var(--chart-muted)";

function groupColor(key: string | null, bands: RiskLevel[]): string {
  if (!key) return GROUP_FALLBACK;
  if ((bands as string[]).includes(key)) return RISK_COLOR[key as RiskLevel];
  // deterministic pastel for non-risk categories
  let h = 0;
  for (let i = 0; i < key.length; i += 1) h = (h * 31 + key.charCodeAt(i)) % 360;
  return `hsl(${h}, 42%, 52%)`;
}

/** Request keys are parameter JSON; the descriptions below turn them back into
 *  human labels for the stale marker and the screen-reader announcements. */
function parseKey<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export default function Distributions() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabKey>("corr");
  // One request for the feature catalogue; failure retries in place instead of
  // reloading the whole page.
  const catalogReq = useRequest<FeatureCatalog>("features", (signal) => getFeatures(signal));
  const catalog = catalogReq.data;

  if (catalogReq.error && !catalog) {
    return (
      <div>
        <div className="kicker">{t("distributions.kicker")}</div>
        <h1>{t("distributions.err_title")}</h1>
        <ErrorNote error={catalogReq.error} onRetry={catalogReq.reload} />
      </div>
    );
  }
  if (!catalog) {
    return (
      <div>
        <div className="kicker">{t("distributions.kicker")}</div>
        <h1>{t("distributions.title")}</h1>
        <Skeleton rows={3} height={44} />
        <Skeleton rows={6} />
      </div>
    );
  }

  const cats = catalog.categories;
  const feat = catalog.features;
  const usable = feat.filter((f) => f.available);
  const bands = cats.find((c) => c.key === "risk_level");

  return (
    <div>
      <PageHead
        kicker={t("distributions.kicker")}
        title={t("distributions.title")}
        lede={t("distributions.lede", { n: int(catalog.n_rows) })}
      />

      <div className="callout warn">
        <Trans i18nKey="distributions.callout" components={{ strong: <strong />, sup: <sup /> }} />
      </div>

      <Tabs<TabKey>
        panelId="distribution-panel"
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "corr", label: t("distributions.tab_corr") },
          { key: "dist", label: t("distributions.tab_dist") },
          { key: "rel", label: t("distributions.tab_rel") },
          { key: "mix", label: t("distributions.tab_mix") },
        ]}
      />

      <div id="distribution-panel" role="tabpanel" aria-labelledby={`distribution-panel-${tab}`}>
      {tab === "corr" && <CorrelationsTab features={usable} />}
      {tab === "dist" && <DistributionsTab features={usable} cats={cats} />}
      {tab === "rel" && (
        <RelationshipsTab features={usable} cats={cats} bands={bands ? [bands.key] : []} />
      )}
      {tab === "mix" && <CompositionTab features={usable} cats={cats} />}
      </div>
    </div>
  );
}

/* ==========================================================================
   Correlations
   ========================================================================== */
function CorrelationsTab({ features }: { features: FeatureCatalog["features"] }) {
  const { t } = useTranslation();
  const [method, setMethod] = useState("spearman");
  const [picked, setPicked] = useState<string[]>(
    [
      "award_total_mdl",
      "estimated_value_mdl",
      "n_bidders",
      "bid_window_days",
      "buyer_supplier_repeat_share",
      "value_vs_cpv_median",
    ].filter((k) => features.some((f) => f.key === k)),
  );
  const enabled = picked.length >= 2;
  const key = JSON.stringify({ method, features: picked });
  const req = useRequest<Correlations>(
    key,
    (signal) => getCorrelations({ features: picked, method, top: 40 }, signal),
    enabled,
  );

  const label = (k: string) => labelOf(features.find((f) => f.key === k)?.label ?? k);
  const describe = (raw: string) => {
    const p = parseKey<{ method: string; features: string[] }>(raw, { method, features: [] });
    return t("distributions.params_corr", {
      method: t(`distributions.method_${p.method}`),
      n: p.features.length,
    });
  };

  return (
    <>
      <Panel
        title={t("distributions.corr_h")}
        note={t("distributions.corr_p")}
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label={t("distributions.f_method")}>
              <select value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="spearman">{t("distributions.method_spearman")}</option>
                <option value="pearson">{t("distributions.method_pearson")}</option>
                <option value="kendall">{t("distributions.method_kendall")}</option>
              </select>
            </Field>
            <Field label={t("distributions.f_features")}>
              <select
                multiple
                size={6}
                value={picked}
                onChange={(e) =>
                  setPicked(Array.from(e.target.selectedOptions, (o) => o.value))
                }
                style={{ minWidth: 250, minHeight: 120 }}
              >
                {features.map((f) => (
                  <option key={f.key} value={f.key}>
                    {labelOf(f.label)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        }
      >
        {!enabled ? (
          <Empty title={t("distributions.pick_two")} hint={t("distributions.pick_two_hint")} />
        ) : (
          <RequestPanel
            state={req}
            describe={describe}
            loadingLabel={t("distributions.computing")}
            isEmpty={(data) => data.columns.length < 2}
            emptyTitle={t("distributions.corr_empty")}
            emptyHint={t("distributions.corr_empty_hint")}
          >
            {(data) => (
              <>
                <div className="corr-grid" style={{ gridTemplateColumns: `repeat(${data.columns.length + 1}, minmax(52px, 1fr))` }}>
                  <div className="corr-cell head" />
                  {data.columns.map((c) => (
                    <div className="corr-cell head" key={`h-${c}`}>
                      {label(c)}
                    </div>
                  ))}
                  {data.columns.map((rowKey, i) => (
                    <Fragment key={rowKey}>
                      <div className="corr-cell head" key={`r-${rowKey}`}>
                        {label(rowKey)}
                      </div>
                      {data.columns.map((colKey, j) => {
                        const v = data.matrix[i]?.[j] ?? null;
                        return (
                          <div
                            className="corr-cell"
                            key={`${rowKey}-${colKey}`}
                            style={{ background: corrColor(v) }}
                            title={t("distributions.cell_title", {
                              a: label(rowKey),
                              b: label(colKey),
                              r: v === null ? t("distributions.na") : v.toFixed(3),
                            })}
                          >
                            {v === null ? "–" : v.toFixed(2)}
                          </div>
                        );
                      })}
                    </Fragment>
                  ))}
                </div>
                <div className="corr-legend">
                  <span>−1</span>
                  <span className="ramp" />
                  <span>+1</span>
                  <span className="muted">
                    {t("distributions.legend", {
                      method,
                      n: int(data.n),
                      min: data.min_pairs,
                    })}
                  </span>
                </div>
              </>
            )}
          </RequestPanel>
        )}
      </Panel>

      <Panel
        title={t("distributions.pairs_h")}
        note={t("distributions.pairs_p")}
      >
        {!enabled ? (
          <Empty title={t("distributions.pick_two")} hint={t("distributions.pick_two_hint")} />
        ) : (
          <RequestPanel
            state={req}
            describe={describe}
            pending={<Skeleton rows={5} />}
            isEmpty={(data) => data.pairs.length === 0}
            emptyTitle={t("distributions.pairs_empty")}
          >
            {(data) => (
              <TableWrap wide>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">{t("distributions.th_feat_a")}</th>
                      <th scope="col">{t("distributions.th_feat_b")}</th>
                      <th scope="col">{t("distributions.th_r")}</th>
                      <th scope="col">{t("distributions.th_abs_r")}</th>
                      <th scope="col">{t("distributions.th_direction")}</th>
                      <th scope="col">{t("distributions.th_rows")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.pairs.map((p) => (
                      <tr key={`${p.a}-${p.b}`}>
                        <td>{label(p.a)}</td>
                        <td>{label(p.b)}</td>
                        <td className="mono">{p.r.toFixed(3)}</td>
                        <td className="mono">{num1(p.abs_r)}</td>
                        <td>{labelOf(p.direction)}</td>
                        <td className="mono">{int(p.n)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            )}
          </RequestPanel>
        )}
      </Panel>

      <Panel
        title={t("distributions.cov_h")}
        note={t("distributions.cov_p")}
      >
        <TableWrap wide>
          <table>
            <thead>
              <tr>
                <th scope="col">{t("distributions.th_feature")}</th>
                <th scope="col">{t("distributions.th_group")}</th>
                <th scope="col">{t("distributions.th_present")}</th>
                <th scope="col">{t("distributions.th_missing")}</th>
                <th scope="col">{t("distributions.th_median")}</th>
                <th scope="col">{t("distributions.th_iqr")}</th>
                <th scope="col">{t("distributions.th_max")}</th>
              </tr>
            </thead>
            <tbody>
              {features.map((f) => (
                <tr key={f.key}>
                  <td>{labelOf(f.label)}</td>
                  <td className="muted">{labelOf(f.group)}</td>
                  <td className="mono">{int(f.n)}</td>
                  <td className="mono">
                    {f.missing_rate === null ? "—" : pct(f.missing_rate)}
                  </td>
                  <td className="mono">{val(f.summary?.median)}</td>
                  <td className="mono">
                    {val(f.summary?.p25)} – {val(f.summary?.p75)}
                  </td>
                  <td className="mono">{val(f.summary?.max)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </Panel>
    </>
  );
}

/* ==========================================================================
   Distributions
   ========================================================================== */
function DistributionsTab({
  features,
  cats,
}: {
  features: FeatureCatalog["features"];
  cats: CategoryMeta[];
}) {
  const { t } = useTranslation();
  const [column, setColumn] = useState("award_total_mdl");
  const [scale, setScale] = useState("auto");
  const [group, setGroup] = useState("");
  const key = JSON.stringify({ column, scale, group });
  const req = useRequest<Distribution>(key, (signal) =>
    getDistribution({ column, bins: 44, group: group || undefined, scale }, signal),
  );

  const describe = (raw: string) => {
    const p = parseKey<{ column: string; scale: string; group: string }>(raw, {
      column,
      scale,
      group,
    });
    return t("distributions.params_dist", {
      feature: labelOf(features.find((f) => f.key === p.column)?.label ?? p.column),
      scale: t(`distributions.scale_${p.scale}`),
      split: p.group
        ? labelOf(cats.find((c) => c.key === p.group)?.label ?? p.group)
        : t("distributions.split_none"),
    });
  };

  const fresh = !req.loading && !req.error && req.dataKey === req.key ? req.data : null;

  return (
    <>
      <Panel
        title={t("distributions.dist_h")}
        note={t("distributions.dist_p")}
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label={t("distributions.f_feature")}>
              <select value={column} onChange={(e) => setColumn(e.target.value)}>
                {features.map((f) => (
                  <option key={f.key} value={f.key}>
                    {labelOf(f.label)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("distributions.f_scale")}>
              <select value={scale} onChange={(e) => setScale(e.target.value)}>
                <option value="auto">{t("distributions.scale_auto")}</option>
                <option value="log">{t("distributions.scale_log")}</option>
                <option value="quantile">{t("distributions.scale_quantile")}</option>
                <option value="linear">{t("distributions.scale_linear")}</option>
              </select>
            </Field>
            <Field label={t("distributions.f_split")}>
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                <option value="">{t("distributions.split_none")}</option>
                {cats.map((c) => (
                  <option key={c.key} value={c.key}>
                    {labelOf(c.label)}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        }
      >
        <RequestPanel
          state={req}
          describe={describe}
          pending={<Skeleton rows={6} height={30} />}
          isEmpty={(data) => data.bins.length === 0 && data.summary === null}
          emptyTitle={t("distributions.dist_empty")}
          emptyHint={t("distributions.dist_empty_hint")}
        >
          {(data) => <DistributionBody data={data} />}
        </RequestPanel>
      </Panel>

      {/*
        The by-group table only ever shows results for the current split: while
        a new split loads it is hidden instead of lingering under a chart that
        is already marked as updating.
      */}
      {group && fresh && fresh.groups.length > 0 && (
        <Panel
          title={t("distributions.median_by", {
            group: labelOf(cats.find((c) => c.key === group)?.label ?? group),
          })}
          note={t("distributions.median_by_p")}
        >
          <TableWrap>
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("distributions.th_group")}</th>
                  <th scope="col">{t("distributions.th_n")}</th>
                  <th scope="col">{t("distributions.th_share")}</th>
                  <th scope="col">{t("distributions.th_p25")}</th>
                  <th scope="col">{t("distributions.th_median")}</th>
                  <th scope="col">{t("distributions.th_p75")}</th>
                  <th scope="col">{t("distributions.th_mean")}</th>
                </tr>
              </thead>
              <tbody>
                {fresh.groups.map((g) => (
                  <tr key={g.key}>
                    <td>{labelOf(g.label)}</td>
                    <td className="mono">{int(g.n)}</td>
                    <td className="mono">{pct(g.share)}</td>
                    <td className="mono">{axisFmt(g.p25)}</td>
                    <td className="mono">{axisFmt(g.median)}</td>
                    <td className="mono">{axisFmt(g.p75)}</td>
                    <td className="mono">{axisFmt(g.mean)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </Panel>
      )}
      {group && fresh && fresh.groups.length === 0 && (
        <Empty title={t("distributions.median_by_empty")} hint={t("distributions.median_by_empty_hint")} />
      )}
    </>
  );
}

function DistributionBody({ data }: { data: Distribution }) {
  const { t } = useTranslation();
  const s = data.summary;
  const ecdf = useMemo(
    () => (data.ecdf ?? []).map(([x, y]) => ({ x: x as number, y: (y as number) * 100 })),
    [data],
  );
  const bins = useMemo(
    () => (data.bins ?? []).map((b) => ({ label: axisFmt(b.mid), n: b.n })),
    [data],
  );
  const usedLog = data.scale === "log";

  return (
    <>
      {s && (
        <MiniStats
          items={[
            { label: t("distributions.stat_n"), value: int(s.n) },
            { label: t("distributions.stat_median"), value: axisFmt(s.median) },
            { label: t("distributions.stat_p99"), value: axisFmt(s.p99) },
            { label: t("distributions.stat_max"), value: axisFmt(s.max) },
            {
              label: t("distributions.stat_iqr"),
              value: pct(s.iqr_outlier_rate),
              tone: s.iqr_outlier_rate > 0.15 ? "warn" : "muted",
            },
            {
              label: t("distributions.stat_zeros"),
              value: int(s.zeros),
              tone: s.zeros > 0 ? "muted" : undefined,
            },
          ]}
        />
      )}
      {usedLog && (
        <p className="chart-note">
          {t("distributions.log_note", {
            ratio: s?.skew_ratio
              ? t("distributions.log_times", { n: axisFmt(s.skew_ratio) })
              : t("distributions.log_far"),
          })}
        </p>
      )}
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={bins} margin={{ top: 6, right: 12, bottom: 4, left: -12 }}>
          <CartesianGrid stroke="var(--line-soft)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 10, fill: "var(--muted)" }}
            tickLine={false}
            axisLine={{ stroke: "var(--line)" }}
            interval="preserveStartEnd"
            minTickGap={8}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "var(--muted)" }}
            tickLine={false}
            axisLine={false}
            width={48}
          />
          <Tooltip
            formatter={(v: number | string) => [int(Number(v)), t("distributions.tooltip_procedures")]}
            labelFormatter={(l) => t("distributions.tooltip_value", { v: l })}
          />
          <Bar dataKey="n" fill="var(--chart-blue)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>

      <h3 style={{ marginTop: 22 }}>{t("distributions.ecdf_h")}</h3>
      <p className="muted">{t("distributions.ecdf_p")}</p>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={ecdf} margin={{ top: 6, right: 12, bottom: 4, left: -18 }}>
          <CartesianGrid stroke="var(--line-soft)" vertical={false} />
          <XAxis
            dataKey="x"
            type="number"
            scale={usedLog ? "log" : "linear"}
            tickFormatter={axisFmt}
            tick={{ fontSize: 10, fill: "var(--muted)" }}
            tickLine={false}
            axisLine={{ stroke: "var(--line)" }}
            minTickGap={26}
          />
          <YAxis
            domain={[0, 100]}
            tickFormatter={(v) => `${v}%`}
            tick={{ fontSize: 11, fill: "var(--muted)" }}
            tickLine={false}
            axisLine={false}
            width={48}
          />
          <Tooltip
            formatter={(v: number | string) => [`${Number(v).toFixed(1)}%`, t("distributions.tooltip_cumulative")]}
            labelFormatter={(l) => t("distributions.tooltip_value_plain", { v: axisFmt(Number(l)) })}
          />
          {[25, 50, 75, 90].map((q) => (
            <ReferenceLine
              key={q}
              y={q}
              stroke="var(--chart-gold)"
              strokeDasharray="3 3"
              label={{ value: `p${q}`, position: "insideLeft", fontSize: 10, fill: "var(--chart-gold)" }}
            />
          ))}
          <Line type="stepAfter" dataKey="y" stroke="var(--chart-blue)" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </>
  );
}

/* ==========================================================================
   Relationships
   ========================================================================== */
function RelationshipsTab({
  features,
  cats,
  bands,
}: {
  features: FeatureCatalog["features"];
  cats: CategoryMeta[];
  bands: string[];
}) {
  const { t } = useTranslation();
  const [x, setX] = useState("estimated_value_mdl");
  const [y, setY] = useState("award_total_mdl");
  const [group, setGroup] = useState("risk_level");
  const [logAxes, setLogAxes] = useState(true);
  const [value, setValue] = useState("award_total_mdl");
  // The spread chart owns its scale: the scatter's log setting must not drag a
  // quartile axis along with it (quartiles ≤ 0 are not log-plottable).
  const [spreadScale, setSpreadScale] = useState<ScaleRequest>("auto");

  const scatterKey = JSON.stringify({ x, y, group, logAxes });
  const scatterReq = useRequest<ScatterData>(scatterKey, (signal) =>
    getScatter({ x, y, group: group || undefined, limit: 3500, log_x: logAxes, log_y: logAxes }, signal),
  );
  const cmpKey = JSON.stringify({ value, group });
  const cmpReq = useRequest<GroupCompare>(cmpKey, (signal) =>
    getGroupCompare({ value, group: group || "procedure", limit: 12 }, signal),
  );

  const featLabel = (key: string) =>
    labelOf(features.find((f) => f.key === key)?.label ?? key);
  const catLabel = (key: string) =>
    key ? labelOf(cats.find((c) => c.key === key)?.label ?? key) : t("distributions.split_none");

  const describeScatter = (raw: string) => {
    const p = parseKey<{ x: string; y: string; group: string; logAxes: boolean }>(raw, {
      x,
      y,
      group,
      logAxes,
    });
    return t("distributions.params_rel", {
      x: featLabel(p.x),
      y: featLabel(p.y),
      group: catLabel(p.group),
      scale: p.logAxes ? t("distributions.log_yes") : t("distributions.log_no"),
    });
  };
  const describeSpread = (raw: string) => {
    const p = parseKey<{ value: string; group: string }>(raw, { value, group });
    return t("distributions.params_spread", {
      measure: featLabel(p.value),
      group: catLabel(p.group),
    });
  };

  const byGroup = useMemo(() => {
    const map = new Map<string, { x: number; y: number; g: string }[]>();
    for (const p of scatterReq.data?.points ?? []) {
      const k = p.g ?? "(none)";
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push({ x: p.x, y: p.y, g: k });
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1].length - a[1].length)
      .slice(0, 8);
  }, [scatterReq.data]);

  return (
    <>
      <Panel
        title={t("distributions.rel_h")}
        note={t("distributions.rel_p")}
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label={t("distributions.f_x")}>
              <select value={x} onChange={(e) => setX(e.target.value)}>
                {features.map((f) => (
                  <option key={f.key} value={f.key}>
                    {labelOf(f.label)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("distributions.f_y")}>
              <select value={y} onChange={(e) => setY(e.target.value)}>
                {features.map((f) => (
                  <option key={f.key} value={f.key}>
                    {labelOf(f.label)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("distributions.f_colour")}>
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                <option value="">{t("distributions.split_none")}</option>
                {cats.map((c) => (
                  <option key={c.key} value={c.key}>
                    {labelOf(c.label)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("distributions.f_log")}>
              <select
                value={logAxes ? "1" : "0"}
                onChange={(e) => setLogAxes(e.target.value === "1")}
              >
                <option value="1">{t("distributions.log_yes")}</option>
                <option value="0">{t("distributions.log_no")}</option>
              </select>
            </Field>
          </div>
        }
      >
        <RequestPanel
          state={scatterReq}
          describe={describeScatter}
          loadingLabel={t("distributions.computing")}
          pending={<Skeleton rows={8} height={30} />}
          isEmpty={(data) => data.points.length === 0}
          emptyTitle={t("distributions.rel_empty")}
          emptyHint={t("distributions.rel_empty_hint")}
        >
          {(scatter) => (
            <>
              <MiniStats
                items={[
                  { label: t("distributions.stat_paired"), value: int(scatter.n) },
                  { label: t("distributions.stat_plotted"), value: int(scatter.sampled) },
                  {
                    label: t("distributions.stat_pearson"),
                    value: scatter.fit?.r === null || scatter.fit === null ? "—" : num1(scatter.fit.r),
                    tone: Math.abs(scatter.fit?.r ?? 0) > 0.5 ? "warn" : "muted",
                  },
                  { label: t("distributions.stat_slope"), value: scatter.fit ? axisFmt(scatter.fit.slope) : "—" },
                ]}
              />
              {scatter.fit && (
                <p className="chart-note">
                  {t("distributions.fit_note", { r: num1(scatter.fit.r ?? 0) })}
                </p>
              )}
              {byGroup.length === 0 ? (
                <Empty title={t("distributions.rel_empty")} hint={t("distributions.rel_empty_hint")} />
              ) : (
                <>
                  <ResponsiveContainer width="100%" height={360}>
                    <ScatterChart margin={{ top: 8, right: 16, bottom: 28, left: 4 }}>
                      <CartesianGrid stroke="var(--line-soft)" />
                      <XAxis
                        type="number"
                        dataKey="x"
                        name={labelOf(scatter.x_label)}
                        scale={logAxes ? "log" : "linear"}
                        domain={["auto", "auto"]}
                        tickFormatter={axisFmt}
                        tick={{ fontSize: 10, fill: "var(--muted)" }}
                        tickLine={false}
                        axisLine={{ stroke: "var(--line)" }}
                        label={{ value: labelOf(scatter.x_label), position: "insideBottom", offset: -14, fontSize: 11, fill: "var(--muted)" }}
                      />
                      <YAxis
                        type="number"
                        dataKey="y"
                        name={labelOf(scatter.y_label)}
                        scale={logAxes ? "log" : "linear"}
                        domain={["auto", "auto"]}
                        tickFormatter={axisFmt}
                        tick={{ fontSize: 10, fill: "var(--muted)" }}
                        tickLine={false}
                        axisLine={false}
                        width={58}
                        label={{ value: labelOf(scatter.y_label), angle: -90, position: "insideLeft", fontSize: 11, fill: "var(--muted)" }}
                      />
                      <ZAxis range={[22, 22]} />
                      <Tooltip
                        cursor={{ strokeDasharray: "3 3" }}
                        formatter={(v: number | string, name: string) => [axisFmt(Number(v)), name]}
                      />
                      {byGroup.map(([key, points]) => (
                        <Scatter
                          key={key}
                          name={labelOf(key)}
                          data={points}
                          fill={groupColor(key, bands as RiskLevel[])}
                          fillOpacity={0.5}
                          isAnimationActive={false}
                        />
                      ))}
                    </ScatterChart>
                  </ResponsiveContainer>
                  <ul className="legend">
                    {byGroup.map(([key, pts]) => (
                      <li key={key}>
                        <span className="swatch" style={{ background: groupColor(key, bands as RiskLevel[]) }} />
                        {labelOf(key)} · {int(pts.length)}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </RequestPanel>
      </Panel>

      <Panel
        title={t("distributions.spread_h")}
        note={t("distributions.spread_p")}
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label={t("distributions.f_measure")}>
              <select value={value} onChange={(e) => setValue(e.target.value)}>
                {features.map((f) => (
                  <option key={f.key} value={f.key}>
                    {labelOf(f.label)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("distributions.f_groupby")}>
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                {cats.map((c) => (
                  <option key={c.key} value={c.key}>
                    {labelOf(c.label)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("distributions.f_spread_scale")}>
              <select
                value={spreadScale}
                onChange={(e) => setSpreadScale(e.target.value as ScaleRequest)}
              >
                <option value="auto">{t("distributions.scale_auto")}</option>
                <option value="log">{t("distributions.scale_log")}</option>
                <option value="linear">{t("distributions.scale_linear")}</option>
              </select>
            </Field>
          </div>
        }
      >
        <RequestPanel
          state={cmpReq}
          describe={describeSpread}
          pending={<Skeleton rows={5} height={28} />}
          isEmpty={(data) => data.groups.length === 0}
          emptyTitle={t("distributions.spread_empty")}
          emptyHint={t("distributions.spread_empty_hint")}
        >
          {(cmp) => {
            const rows: QuartileRow[] = cmp.groups.map((g) => ({
              key: g.key,
              name: g.key.length > 20 ? `${g.key.slice(0, 19)}…` : g.key,
              full: g.key,
              p25: g.p25,
              median: g.median,
              p75: g.p75,
              n: g.n,
            }));
            // Notes only need the scale *decisions* (which rows a log axis keeps
            // and refuses), so this probe uses an arbitrary plot width.
            const probe = buildQuartileLayout({ rows, requested: spreadScale, plotWidth: 1000 });
            const undrawable = rows.filter((row) => classifyQuartileRow(row) !== "valid");
            const nonPositive = nonPositiveQuartileRows(rows);
            return (
              <>
                <QuartileRangeChart
                  rows={rows}
                  scale={spreadScale}
                  fmt={axisFmt}
                  measureLabel={cmp.value_label}
                />
                <p className="chart-note">
                  {t("distributions.spread_note")}{" "}
                  {probe.excluded.length > 0 &&
                    t("distributions.spread_log_note", {
                      count: probe.excluded.length,
                      names: probe.excluded.map((row) => row.name).join(", "),
                    })}{" "}
                  {probe.logRefused &&
                    nonPositive.length > 0 &&
                    t("distributions.spread_log_fallback", {
                      names: nonPositive.map((row) => row.full).join(", "),
                    })}{" "}
                  {undrawable.length > 0 &&
                    t("distributions.spread_undrawable", { count: undrawable.length })}{" "}
                  {cmp.dropped_groups > 0 &&
                    t("distributions.dropped_groups", { count: cmp.dropped_groups })}
                </p>
                <ul className="legend">
                  <li>
                    <i className="legend-marker range" />
                    {t("distributions.spread_legend_interval")}
                  </li>
                  <li>
                    <i className="legend-marker median" />
                    {t("distributions.spread_legend_median")}
                  </li>
                </ul>
                <details className="research-disclosure">
                  <summary>{t("distributions.spread_raw_table")}</summary>
                  <TableWrap>
                    <table>
                      <caption className="muted">{cmp.value_label}</caption>
                      <thead>
                        <tr>
                          <th scope="col">{t("distributions.th_group")}</th>
                          <th scope="col">{t("distributions.th_n")}</th>
                          <th scope="col">{t("distributions.th_p25")}</th>
                          <th scope="col">{t("distributions.th_median")}</th>
                          <th scope="col">{t("distributions.th_p75")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {cmp.groups.map((g) => (
                          <tr key={g.key}>
                            <th scope="row">{g.key}</th>
                            <td className="mono">{int(g.n)}</td>
                            <td className="mono">{axisFmt(g.p25)}</td>
                            <td className="mono">{axisFmt(g.median)}</td>
                            <td className="mono">{axisFmt(g.p75)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                </details>
              </>
            );
          }}
        </RequestPanel>
      </Panel>
    </>
  );
}

/* ==========================================================================
   Composition
   ========================================================================== */
function CompositionTab({
  features,
  cats,
}: {
  features: FeatureCatalog["features"];
  cats: CategoryMeta[];
}) {
  const { t } = useTranslation();
  const [a, setA] = useState("procedure");
  const [b, setB] = useState("risk_level");
  const [value, setValue] = useState("");
  const key = JSON.stringify({ a, b, value });
  const req = useRequest<Crosstab>(key, (signal) =>
    getCrosstab({ a, b, value: value || undefined, limit: 16 }, signal),
  );

  const describe = (raw: string) => {
    const p = parseKey<{ a: string; b: string; value: string }>(raw, { a, b, value });
    return t("distributions.params_mix", {
      a: labelOf(cats.find((c) => c.key === p.a)?.label ?? p.a),
      b: labelOf(cats.find((c) => c.key === p.b)?.label ?? p.b),
      measure: p.value
        ? t("distributions.measure_sum", {
            label: labelOf(features.find((f) => f.key === p.value)?.label ?? p.value),
          })
        : t("distributions.measure_count"),
    });
  };

  return (
    <Panel
      title={t("distributions.mix_h")}
      note={t("distributions.mix_p")}
      actions={
        <div className="toolbar" style={{ margin: 0 }}>
          <Field label={t("distributions.f_rows")}>
            <select value={a} onChange={(e) => setA(e.target.value)}>
              {cats.map((c) => (
                <option key={c.key} value={c.key}>
                  {labelOf(c.label)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("distributions.f_cols")}>
            <select value={b} onChange={(e) => setB(e.target.value)}>
              {cats.map((c) => (
                <option key={c.key} value={c.key}>
                  {labelOf(c.label)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("distributions.f_measure")}>
            <select value={value} onChange={(e) => setValue(e.target.value)}>
              <option value="">{t("distributions.measure_count")}</option>
              {features.map((f) => (
                <option key={f.key} value={f.key}>
                  {t("distributions.measure_sum", { label: labelOf(f.label) })}
                </option>
              ))}
            </select>
          </Field>
        </div>
      }
    >
      <RequestPanel
        state={req}
        describe={describe}
        pending={<Skeleton rows={6} height={26} />}
        isEmpty={(data) => data.rows.length === 0}
        emptyTitle={t("distributions.mix_empty")}
        emptyHint={t("distributions.mix_empty_hint")}
      >
        {(data) => (
          <>
            <div className="table-wrap wide">
              <table>
                <thead>
                  <tr>
                    <th scope="col">
                      {labelOf(data.a_label)} ╲ {labelOf(data.b_label)}
                    </th>
                    {data.cols.map((c) => (
                      <th scope="col" key={c}>
                        {labelOf(c)}
                      </th>
                    ))}
                    <th scope="col">{t("distributions.th_total")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r, i) => {
                    const row = data.matrix[i] ?? [];
                    const total = row.reduce<number>((acc, v) => acc + (v ?? 0), 0);
                    return (
                      <tr key={r}>
                        <th scope="row" style={{ background: "var(--surface-secondary)" }}>
                          {labelOf(r)}
                        </th>
                        {row.map((v, j) => {
                          const share = data.max ? (v ?? 0) / data.max : 0;
                          // Semantic heat token, capped at 55% so the number keeps
                          // AA contrast on its own background in both themes.
                          const intensity = Math.round(Math.min(Math.max(share, 0), 1) * 55);
                          return (
                            <td
                              key={data.cols[j]}
                              className="mono"
                              style={{
                                background: `color-mix(in srgb, var(--chart-heat) ${intensity}%, var(--card))`,
                                textAlign: "right",
                              }}
                            >
                              {v === null ? "–" : num(v)}
                            </td>
                          );
                        })}
                        <td className="mono" style={{ fontWeight: 600 }}>
                          {num(total)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="chart-note">
              {data.value
                ? t("distributions.cells_sum", {
                    label: labelOf(features.find((f) => f.key === data.value)?.label ?? data.value),
                  })
                : t("distributions.cells_count")}{" "}
              {t("distributions.mix_intensity")}{" "}
              {data.dropped > 0 && t("distributions.dropped_levels", { count: data.dropped })}
            </p>
          </>
        )}
      </RequestPanel>
    </Panel>
  );
}
