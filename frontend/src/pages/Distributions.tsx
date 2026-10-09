import { useEffect, useMemo, useState } from "react";
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
  Panel,
  Skeleton,
  Tabs,
  TableWrap,
  corrColor,
} from "../ui";

type TabKey = "corr" | "dist" | "rel" | "mix";

/** Big or small numbers should not silently become "0" in a chart axis. */
function axisFmt(v: number): string {
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 1e9) return `${(v / 1e9).toFixed(1)}bn`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(1)}m`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}k`;
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
        <div className="kicker">Chapter 3 · distributions</div>
        <h1>Analytics unavailable</h1>
        <ErrorNote error={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }
  if (!catalog) {
    return (
      <div>
        <div className="kicker">Chapter 3 · distributions</div>
        <h1>Distributions &amp; correlations</h1>
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
      <div className="kicker">Chapter 3 · distributions</div>
      <h1>Distributions &amp; correlations</h1>
      <p className="lede">
        Computed server-side over all {int(catalog.n_rows)} procedures, not over the 1,500-row
        detector sample. Correlations use pairwise-complete observations, so a feature that is
        missing for part of the corpus is compared only on rows where both features exist.
      </p>

      <div className="callout warn">
        <strong>Read the correlation method before the numbers.</strong> Award values in this
        corpus reach about 5×10<sup>13</sup> MDL while the median is under 2×10<sup>4</sup>. On
        such a distribution Pearson&apos;s r is dominated by a handful of mega-contracts and
        reports almost nothing — Pearson puts award total against estimated value at r≈0.18,
        Spearman at r≈0.99. Spearman is the default below for that reason; the Pearson figure is
        kept so the difference is visible rather than hidden.
      </div>

      <Tabs<TabKey>
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "corr", label: "Correlations" },
          { key: "dist", label: "Distributions" },
          { key: "rel", label: "Relationships" },
          { key: "mix", label: "Composition" },
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

  const label = (k: string) => features.find((f) => f.key === k)?.label ?? k;

  return (
    <>
      <Panel
        title="Correlation matrix"
        note="Cells are the correlation coefficient; colour is teal for negative, gold for positive, and opacity follows magnitude. Computed on rows where both features are present."
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label="Method">
              <select value={method} onChange={(e) => setMethod(e.target.value)}>
                <option value="spearman">Spearman (rank)</option>
                <option value="pearson">Pearson (linear)</option>
                <option value="kendall">Kendall (tau)</option>
              </select>
            </Field>
            <Field label="Features">
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
                    {f.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        }
      >
        {error && <ErrorNote error={error} />}
        {busy && !data && <Loading label="Computing matrix…" />}
        {!busy && !data && picked.length < 2 && (
          <Empty title="Pick at least two features" hint="Ctrl/Cmd-click in the list to select several." />
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
                        title={`${label(rowKey)} × ${label(colKey)}: r = ${v === null ? "n/a" : v.toFixed(3)}`}
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
                {method} · {int(data.n)} rows · minimum {data.min_pairs} paired observations
              </span>
            </div>
          </>
        )}
      </Panel>

      <Panel
        title="Strongest pairs"
        note="Ranked by |r|. The n column is the number of rows the coefficient was computed on — a correlation on a few hundred rows is not comparable with one on the full corpus."
      >
        {!data ? (
          <Skeleton rows={5} />
        ) : data.pairs.length === 0 ? (
          <Empty title="No pairs above the minimum sample" />
        ) : (
          <TableWrap wide>
            <table>
              <thead>
                <tr>
                  <th scope="col">Feature A</th>
                  <th scope="col">Feature B</th>
                  <th scope="col">r</th>
                  <th scope="col">|r|</th>
                  <th scope="col">Direction</th>
                  <th scope="col">Rows</th>
                </tr>
              </thead>
              <tbody>
                {data.pairs.map((p) => (
                  <tr key={`${p.a}-${p.b}`}>
                    <td>{label(p.a)}</td>
                    <td>{label(p.b)}</td>
                    <td className="mono">{p.r.toFixed(3)}</td>
                    <td className="mono">{num1(p.abs_r)}</td>
                    <td>{p.direction}</td>
                    <td className="mono">{int(p.n)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Panel>

      <Panel
        title="Feature coverage"
        note="A feature missing for most of the corpus can still be correlated, but only on the rows where it exists. The minimum is shown so a thin sample is not mistaken for a full-corpus result."
      >
        <TableWrap wide>
          <table>
            <thead>
              <tr>
                <th scope="col">Feature</th>
                <th scope="col">Group</th>
                <th scope="col">Present</th>
                <th scope="col">Missing</th>
                <th scope="col">Median</th>
                <th scope="col">p25 – p75</th>
                <th scope="col">Max</th>
              </tr>
            </thead>
            <tbody>
              {features.map((f) => (
                <tr key={f.key}>
                  <td>{f.label}</td>
                  <td className="muted">{f.group}</td>
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
        title="Distribution"
        note="Histogram with percentile markers, plus the empirical CDF. The bin scale is chosen automatically when the data is heavily skewed, because equal-width bins collapse into a single bar."
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label="Feature">
              <select value={column} onChange={(e) => setColumn(e.target.value)}>
                {features.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Bin scale">
              <select value={scale} onChange={(e) => setScale(e.target.value)}>
                <option value="auto">auto (fit the skew)</option>
                <option value="log">logarithmic</option>
                <option value="quantile">quantile (equal count)</option>
                <option value="linear">linear</option>
              </select>
            </Field>
            <Field label="Split by">
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                <option value="">nothing</option>
                {cats.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}
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
              { label: "Observations", value: int(s.n) },
              { label: "Median", value: axisFmt(s.median ?? 0) },
              { label: "p99", value: axisFmt(s.p99 ?? 0) },
              { label: "Max", value: axisFmt(s.max ?? 0) },
              {
                label: "IQR outliers",
                value: pct(s.iqr_outlier_rate),
                tone: s.iqr_outlier_rate > 0.15 ? "warn" : "muted",
              },
              {
                label: "Zeros",
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
                Bins are logarithmic: the largest value is{" "}
                {s?.skew_ratio ? `${axisFmt(s.skew_ratio)}×` : "far"} the median, so equal-width
                bins would put every value but one in the first bar.
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
                  formatter={(v: number | string) => [int(Number(v)), "procedures"]}
                  labelFormatter={(l) => `value ≈ ${l}`}
                />
                <Bar dataKey="n" fill="#1e3a5f" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>

            <h3 style={{ marginTop: 22 }}>Empirical cumulative distribution</h3>
            <p className="muted">
              The share of procedures at or below each value. Read the height at a given x to get
              the percentile directly — no assumption about the distribution shape.
            </p>
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
                  formatter={(v: number | string) => [`${Number(v).toFixed(1)}%`, "cumulative"]}
                  labelFormatter={(l) => `value ${axisFmt(Number(l))}`}
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
        <Panel title={`Median by ${cats.find((c) => c.key === group)?.label ?? group}`} note="Groups below 20 observations are excluded so a single record cannot define a bar.">
          <TableWrap>
            <table>
              <thead>
                <tr>
                  <th scope="col">Group</th>
                  <th scope="col">n</th>
                  <th scope="col">Share</th>
                  <th scope="col">p25</th>
                  <th scope="col">Median</th>
                  <th scope="col">p75</th>
                  <th scope="col">Mean</th>
                </tr>
              </thead>
              <tbody>
                {data.groups.map((g) => (
                  <tr key={g.key}>
                    <td>{g.label}</td>
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
        title="Paired relationship"
        note="Down-sampled with a fixed stride, so the same filters always return the same points and the chart does not jump between renders."
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label="X">
              <select value={x} onChange={(e) => setX(e.target.value)}>
                {features.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Y">
              <select value={y} onChange={(e) => setY(e.target.value)}>
                {features.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Colour by">
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                <option value="">nothing</option>
                {cats.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Log axes">
              <select
                value={logAxes ? "1" : "0"}
                onChange={(e) => setLogAxes(e.target.value === "1")}
              >
                <option value="1">logarithmic</option>
                <option value="0">linear</option>
              </select>
            </Field>
          </div>
        }
      >
        {error && <ErrorNote error={error} />}
        {scatter && (
          <MiniStats
            items={[
              { label: "Paired rows", value: int(scatter.n) },
              { label: "Plotted", value: int(scatter.sampled) },
              {
                label: "Pearson r",
                value: scatter.fit?.r === null || scatter.fit === null ? "—" : num1(scatter.fit.r),
                tone: Math.abs(scatter.fit?.r ?? 0) > 0.5 ? "warn" : "muted",
              },
              { label: "Slope", value: scatter.fit ? axisFmt(scatter.fit.slope) : "—" },
            ]}
          />
        )}
        {scatter?.fit && (
          <p className="chart-note">
            Least-squares fit gives r = {num1(scatter.fit.r ?? 0)} on the raw values. Because the
            axes are logarithmic here, prefer the rank correlation on the previous tab for
            anything involving money — a straight line through log-spaced mega-contracts is not
            evidence of a linear relationship in the raw amounts.
          </p>
        )}
        {!scatter ? (
          <Skeleton rows={8} height={30} />
        ) : byGroup.length === 0 ? (
          <Empty title="No paired values under these choices" hint="Both features must be present on the same row." />
        ) : (
          <>
            <ResponsiveContainer width="100%" height={360}>
              <ScatterChart margin={{ top: 8, right: 16, bottom: 28, left: 4 }}>
                <CartesianGrid stroke="#eee6d8" />
                <XAxis
                  type="number"
                  dataKey="x"
                  name={scatter.x_label}
                  scale={logAxes ? "log" : "linear"}
                  domain={["auto", "auto"]}
                  tickFormatter={axisFmt}
                  tick={{ fontSize: 10, fill: "#5c6673" }}
                  tickLine={false}
                  label={{ value: scatter.x_label, position: "insideBottom", offset: -14, fontSize: 11, fill: "#5c6673" }}
                />
                <YAxis
                  type="number"
                  dataKey="y"
                  name={scatter.y_label}
                  scale={logAxes ? "log" : "linear"}
                  domain={["auto", "auto"]}
                  tickFormatter={axisFmt}
                  tick={{ fontSize: 10, fill: "#5c6673" }}
                  tickLine={false}
                  width={58}
                  label={{ value: scatter.y_label, angle: -90, position: "insideLeft", fontSize: 11, fill: "#5c6673" }}
                />
                <ZAxis range={[22, 22]} />
                <Tooltip
                  cursor={{ strokeDasharray: "3 3" }}
                  formatter={(v: number | string, name: string) => [axisFmt(Number(v)), name]}
                />
                {byGroup.map(([key, points]) => (
                  <Scatter
                    key={key}
                    name={key}
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
                  {key} · {int(pts.length)}
                </li>
              ))}
            </ul>
          </>
        )}
      </Panel>

      <Panel
        title="Spread by group"
        note="Interquartile range per group. A box plot is used rather than a mean bar because the mean of a right-skewed money column is set by its largest value."
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label="Measure">
              <select value={value} onChange={(e) => setValue(e.target.value)}>
                {features.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Group by">
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                {cats.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}
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
                      return row ? `${row.full} · n=${int(row.n)}` : String(l);
                    }}
                  />
                  <Bar dataKey="p25" stackId="q" fill="#9db8d2" isAnimationActive={false} />
                  <Bar dataKey="median" stackId="q" fill="#1e3a5f" isAnimationActive={false} radius={[0, 3, 3, 0]} />
                  <Bar dataKey="p75" stackId="q" fill="#9db8d2" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            <p className="chart-note">
              The bar spans p25 → p75 with the median at the colour change.{" "}
              {cmp.dropped_groups > 0 &&
                `${cmp.dropped_groups} smaller group(s) were dropped for having too few observations.`}
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
      title="Cross-tabulation"
      note="Counts, or the sum of a measure. The busiest levels are kept and the rest reported as dropped, so a truncated matrix never looks complete."
      actions={
        <div className="toolbar" style={{ margin: 0 }}>
          <Field label="Rows">
            <select value={a} onChange={(e) => setA(e.target.value)}>
              {cats.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Columns">
            <select value={b} onChange={(e) => setB(e.target.value)}>
              {cats.map((c) => (
                <option key={c.key} value={c.key}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Measure">
            <select value={value} onChange={(e) => setValue(e.target.value)}>
              <option value="">count</option>
              {features.map((f) => (
                <option key={f.key} value={f.key}>
                  sum of {f.label}
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
        <Empty title="Nothing to cross-tabulate" hint="Pick two different categories." />
      ) : (
        <>
          <div className="table-wrap wide">
            <table>
              <thead>
                <tr>
                  <th scope="col">
                    {data.a_label} ╲ {data.b_label}
                  </th>
                  {data.cols.map((c) => (
                    <th scope="col" key={c}>
                      {c}
                    </th>
                  ))}
                  <th scope="col">total</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => {
                  const row = data.matrix[i] ?? [];
                  const total = row.reduce<number>((a, v) => a + (v ?? 0), 0);
                  return (
                    <tr key={r}>
                      <th scope="row" style={{ background: "#faf6ec" }}>
                        {r}
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
              ? `Cells are the sum of ${features.find((f) => f.key === data.value)?.label ?? data.value}.`
              : "Cells are procedure counts."}{" "}
            {data.dropped > 0 &&
              `${data.dropped} low-frequency level(s) were omitted to keep the matrix legible.`}
          </p>
        </>
      )}
    </Panel>
  );
}
