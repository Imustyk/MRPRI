import { useEffect, useMemo, useState } from "react";
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
import {
  Empty,
  ErrorNote,
  Field,
  Loading,
  MiniStats,
  PageHead,
  Panel,
  Skeleton,
  Tabs,
  TableWrap,
  corrColor,
} from "../ui";

type TabKey = "corr" | "dist" | "rel" | "mix";

const RISK_KEYS = new Set(["unscored", "low", "medium", "high", "critical"]);

/** Localise a backend feature/category/group label, including risk-band keys. */
function labelOf(s: string): string {
  if (s === "(none)") return i18n.t("distributions.none_group");
  if (RISK_KEYS.has(s)) return i18n.t(`risk.${s}`);
  return tr(s);
}

/** Big or small numbers should not silently become "0" in a chart axis. */
function axisFmt(v: number): string {
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}${i18n.t("distributions.axis_bn")}`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}${i18n.t("distributions.axis_m")}`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}${i18n.t("distributions.axis_k")}`;
  if (a < 0.01) return v.toExponential(0);
  return String(Math.round(v * 100) / 100);
}

const GROUP_FALLBACK = "#8a93a0";

function groupColor(key: string | null, bands: RiskLevel[]): string {
  if (!key) return GROUP_FALLBACK;
  if ((bands as string[]).includes(key)) return RISK_COLOR[key as RiskLevel];
  // deterministic pastel for non-risk categories
  let h = 0;
  for (let i = 0; i < key.length; i += 1) h = (h * 31 + key.charCodeAt(i)) % 360;
  return `hsl(${h}, 42%, 52%)`;
}

export default function Distributions() {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<FeatureCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("corr");

  useEffect(() => {
    getFeatures()
      .then(setCatalog)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div>
        <div className="kicker">{t("distributions.kicker")}</div>
        <h1>{t("distributions.err_title")}</h1>
        <ErrorNote error={error} onRetry={() => window.location.reload()} />
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
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "corr", label: t("distributions.tab_corr") },
          { key: "dist", label: t("distributions.tab_dist") },
          { key: "rel", label: t("distributions.tab_rel") },
          { key: "mix", label: t("distributions.tab_mix") },
        ]}
      />

      {tab === "corr" && <CorrelationsTab features={usable} />}
      {tab === "dist" && <DistributionsTab features={usable} cats={cats} />}
      {tab === "rel" && (
        <RelationshipsTab features={usable} cats={cats} bands={bands ? [bands.key] : []} />
      )}
      {tab === "mix" && <CompositionTab features={usable} cats={cats} />}
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
  const [data, setData] = useState<Correlations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (picked.length < 2) return;
    let cancelled = false;
    setBusy(true);
    setError(null);
    getCorrelations({ features: picked, method, top: 40 })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [picked, method]);

  const label = (k: string) =>
    labelOf(features.find((f) => f.key === k)?.label ?? k);

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
        {error && <ErrorNote error={error} />}
        {busy && !data && <Loading label={t("distributions.computing")} />}
        {!busy && !data && picked.length < 2 && (
          <Empty title={t("distributions.pick_two")} hint={t("distributions.pick_two_hint")} />
        )}
        {data && data.columns.length >= 2 && (
          <>
            <div className="corr-grid" style={{ gridTemplateColumns: `repeat(${data.columns.length + 1}, minmax(52px, 1fr))` }}>
              <div className="corr-cell head" />
              {data.columns.map((c) => (
                <div className="corr-cell head" key={`h-${c}`}>
                  {label(c)}
                </div>
              ))}
              {data.columns.map((rowKey, i) => (
                <>
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
                </>
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
      </Panel>

      <Panel
        title={t("distributions.pairs_h")}
        note={t("distributions.pairs_p")}
      >
        {!data ? (
          <Skeleton rows={5} />
        ) : data.pairs.length === 0 ? (
          <Empty title={t("distributions.pairs_empty")} />
        ) : (
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
  const [data, setData] = useState<Distribution | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    getDistribution({ column, bins: 44, group: group || undefined, scale })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [column, scale, group]);

  const s = data?.summary;
  const ecdf = useMemo(
    () => (data?.ecdf ?? []).map(([x, y]) => ({ x: x as number, y: (y as number) * 100 })),
    [data],
  );
  const bins = useMemo(
    () =>
      (data?.bins ?? []).map((b) => ({
        label: b.mid === null ? "–" : axisFmt(b.mid),
        n: b.n,
      })),
    [data],
  );
  const usedLog = data?.scale === "log";

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
        {error && <ErrorNote error={error} />}
        {s && (
          <MiniStats
            items={[
              { label: t("distributions.stat_n"), value: int(s.n) },
              { label: t("distributions.stat_median"), value: axisFmt(s.median ?? 0) },
              { label: t("distributions.stat_p99"), value: axisFmt(s.p99 ?? 0) },
              { label: t("distributions.stat_max"), value: axisFmt(s.max ?? 0) },
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
        {!data ? (
          <Skeleton rows={6} height={30} />
        ) : (
          <>
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
                <CartesianGrid stroke="#eee6d8" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 10, fill: "#5c6673" }}
                  tickLine={false}
                  axisLine={{ stroke: "#d9d0c0" }}
                  interval="preserveStartEnd"
                  minTickGap={8}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "#5c6673" }}
                  tickLine={false}
                  axisLine={false}
                  width={48}
                />
                <Tooltip
                  formatter={(v: number | string) => [int(Number(v)), t("distributions.tooltip_procedures")]}
                  labelFormatter={(l) => t("distributions.tooltip_value", { v: l })}
                />
                <Bar dataKey="n" fill="#1e3a5f" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>

            <h3 style={{ marginTop: 22 }}>{t("distributions.ecdf_h")}</h3>
            <p className="muted">{t("distributions.ecdf_p")}</p>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart
                data={ecdf}
                margin={{ top: 6, right: 12, bottom: 4, left: -18 }}
              >
                <CartesianGrid stroke="#eee6d8" vertical={false} />
                <XAxis
                  dataKey="x"
                  type="number"
                  scale={usedLog ? "log" : "linear"}
                  tickFormatter={axisFmt}
                  tick={{ fontSize: 10, fill: "#5c6673" }}
                  tickLine={false}
                  axisLine={{ stroke: "#d9d0c0" }}
                  minTickGap={26}
                />
                <YAxis
                  domain={[0, 100]}
                  tickFormatter={(v) => `${v}%`}
                  tick={{ fontSize: 11, fill: "#5c6673" }}
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
                    stroke="#b8892a"
                    strokeDasharray="3 3"
                    label={{ value: `p${q}`, position: "insideLeft", fontSize: 10, fill: "#b8892a" }}
                  />
                ))}
                <Line type="stepAfter" dataKey="y" stroke="#1e3a5f" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </>
        )}
      </Panel>

      {group && data && data.groups.length > 0 && (
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
                {data.groups.map((g) => (
                  <tr key={g.key}>
                    <td>{labelOf(g.label)}</td>
                    <td className="mono">{int(g.n)}</td>
                    <td className="mono">{pct(g.share)}</td>
                    <td className="mono">{axisFmt(g.p25 ?? 0)}</td>
                    <td className="mono">{axisFmt(g.median ?? 0)}</td>
                    <td className="mono">{axisFmt(g.p75 ?? 0)}</td>
                    <td className="mono">{axisFmt(g.mean ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        </Panel>
      )}
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
  const [scatter, setScatter] = useState<ScatterData | null>(null);
  const [cmp, setCmp] = useState<GroupCompare | null>(null);
  const [value, setValue] = useState("award_total_mdl");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    getScatter({ x, y, group: group || undefined, limit: 3500, log_x: logAxes, log_y: logAxes })
      .then((d) => {
        if (!cancelled) setScatter(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [x, y, group, logAxes]);

  useEffect(() => {
    let cancelled = false;
    getGroupCompare({ value, group: group || "procedure", limit: 12 })
      .then((d) => {
        if (!cancelled) setCmp(d);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [value, group]);

  const byGroup = useMemo(() => {
    const map = new Map<string, { x: number; y: number; g: string }[]>();
    for (const p of scatter?.points ?? []) {
      const k = p.g ?? "(none)";
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push({ x: p.x, y: p.y, g: k });
    }
    return Array.from(map.entries())
      .sort((a, b) => b[1].length - a[1].length)
      .slice(0, 8);
  }, [scatter]);

  const boxData = useMemo(
    () =>
      (cmp?.groups ?? []).map((g) => ({
        name: g.key.length > 20 ? `${g.key.slice(0, 19)}…` : g.key,
        full: g.key,
        p25: g.p25 ?? 0,
        median: g.median ?? 0,
        p75: g.p75 ?? 0,
        n: g.n,
      })),
    [cmp],
  );

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
        {error && <ErrorNote error={error} />}
        {scatter && (
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
        )}
        {scatter?.fit && (
          <p className="chart-note">
            {t("distributions.fit_note", { r: num1(scatter.fit.r ?? 0) })}
          </p>
        )}
        {!scatter ? (
          <Skeleton rows={8} height={30} />
        ) : byGroup.length === 0 ? (
          <Empty title={t("distributions.rel_empty")} hint={t("distributions.rel_empty_hint")} />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={360}>
              <ScatterChart margin={{ top: 8, right: 16, bottom: 28, left: 4 }}>
                <CartesianGrid stroke="#eee6d8" />
                <XAxis
                  type="number"
                  dataKey="x"
                  name={labelOf(scatter.x_label)}
                  scale={logAxes ? "log" : "linear"}
                  domain={["auto", "auto"]}
                  tickFormatter={axisFmt}
                  tick={{ fontSize: 10, fill: "#5c6673" }}
                  tickLine={false}
                  label={{ value: labelOf(scatter.x_label), position: "insideBottom", offset: -14, fontSize: 11, fill: "#5c6673" }}
                />
                <YAxis
                  type="number"
                  dataKey="y"
                  name={labelOf(scatter.y_label)}
                  scale={logAxes ? "log" : "linear"}
                  domain={["auto", "auto"]}
                  tickFormatter={axisFmt}
                  tick={{ fontSize: 10, fill: "#5c6673" }}
                  tickLine={false}
                  width={58}
                  label={{ value: labelOf(scatter.y_label), angle: -90, position: "insideLeft", fontSize: 11, fill: "#5c6673" }}
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
          </div>
        }
      >
        {!cmp || boxData.length === 0 ? (
          <Skeleton rows={5} height={28} />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={Math.max(220, boxData.length * 30)}>
                <BarChart
                  data={boxData}
                  layout="vertical"
                  margin={{ top: 4, right: 40, bottom: 4, left: 30 }}
                  barCategoryGap={10}
                >
                  <CartesianGrid stroke="#eee6d8" horizontal={false} />
                  <XAxis
                    type="number"
                    scale={logAxes ? "log" : "linear"}
                    tickFormatter={axisFmt}
                    tick={{ fontSize: 10, fill: "#5c6673" }}
                    tickLine={false}
                    axisLine={{ stroke: "#d9d0c0" }}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ fontSize: 11, fill: "#5c6673" }}
                    tickLine={false}
                    axisLine={false}
                    width={168}
                  />
                  <Tooltip
                    formatter={(v: number | string, n) => [axisFmt(Number(v)), String(n)]}
                    labelFormatter={(l) => {
                      const row = boxData.find((b) => b.name === l);
                      return row
                        ? t("distributions.tooltip_n", { name: labelOf(row.full), n: int(row.n) })
                        : String(l);
                    }}
                  />
                  <Bar dataKey="p25" stackId="q" fill="#9db8d2" isAnimationActive={false} />
                  <Bar dataKey="median" stackId="q" fill="#1e3a5f" isAnimationActive={false} radius={[0, 3, 3, 0]} />
                  <Bar dataKey="p75" stackId="q" fill="#9db8d2" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            <p className="chart-note">
              {t("distributions.spread_note")}{" "}
              {cmp.dropped_groups > 0 &&
                t("distributions.dropped_groups", { count: cmp.dropped_groups })}
            </p>
          </>
        )}
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
  const [data, setData] = useState<Crosstab | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    getCrosstab({ a, b, value: value || undefined, limit: 16 })
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [a, b, value]);

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
      {error && <ErrorNote error={error} />}
      {!data ? (
        <Skeleton rows={6} height={26} />
      ) : data.rows.length === 0 ? (
        <Empty title={t("distributions.mix_empty")} hint={t("distributions.mix_empty_hint")} />
      ) : (
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
                  const total = row.reduce<number>((a, v) => a + (v ?? 0), 0);
                  return (
                    <tr key={r}>
                      <th scope="row" style={{ background: "#faf6ec" }}>
                        {labelOf(r)}
                      </th>
                      {row.map((v, j) => {
                        const share = data.max ? (v ?? 0) / data.max : 0;
                        return (
                          <td
                            key={data.cols[j]}
                            className="mono"
                            style={{
                              background: `rgba(30,58,95,${(share * 0.72).toFixed(3)})`,
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
            {data.dropped > 0 && t("distributions.dropped_levels", { count: data.dropped })}
          </p>
        </>
      )}
    </Panel>
  );
}
