import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  getJson,
  int,
  mdl,
  monthLabel,
  num,
  num1,
  pct,
  val,
  type Health,
  type Meta,
  type MongoStatus,
  type RiskLevel,
  type Stats,
} from "../api";
import { Empty, ErrorNote, Skeleton, Stat, TableWrap } from "../ui";

const BAND_ORDER: RiskLevel[] = ["critical", "high", "medium", "low", "unscored"];
const BAND_FILL: Record<string, string> = {
  critical: "#b4232c",
  high: "#c2661f",
  medium: "#c9a02e",
  low: "#2a6b4a",
  unscored: "#c3c8cf",
};

export default function Overview() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [mongo, setMongo] = useState<MongoStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setError(null);
    setLoading(true);
    // stats is the only blocking request; the panels below fill in after it.
    getJson<Stats>("/api/stats")
      .then((d) => {
        setStats(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
    getJson<Meta>("/api/meta").then(setMeta).catch(() => undefined);
    getJson<Health>("/api/health")
      .then((h) => setMongo(h.mongodb))
      .catch(() => undefined);
  };

  useEffect(() => {
    load();
  }, []);

  if (error && !stats) {
    return (
      <div>
        <div className="kicker">Chapter 3 · results</div>
        <h1>Results not available</h1>
        <p className="lede">
          This dashboard reads the real MTender output in <code>data/processed/tenders.json</code> and
          the anomaly scores in MongoDB. Produce them with the ETL:
        </p>
        <pre className="cmd">./scripts/run_pipeline.sh</pre>
        <div style={{ marginTop: 16 }}>
          <ErrorNote error={error} onRetry={load} />
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div>
        <div className="kicker">Republic of Moldova · public procurement</div>
        <h1>Corruption-risk radar</h1>
        <Skeleton rows={4} height={44} />
        <Skeleton rows={5} />
      </div>
    );
  }

  const m = stats.metrics;
  const bandData = BAND_ORDER.filter((b) => stats.level_counts[b]).map((b) => ({
    level: b,
    n: stats.level_counts[b],
  }));
  const months = stats.monthly.map((r) => ({ ...r, label: monthLabel(r.month) }));
  const hasNoPublishedBids = stats.n_with_bid_data === 0;
  // The detection run scored a sample, not the whole corpus. Every share that
  // describes model behaviour must use scored records as its denominator,
  // otherwise "2% high risk" silently means 2% of records no model ever saw.
  const scoredRows = bandData.filter((b) => b.level !== "unscored").reduce((a, b) => a + b.n, 0);
  const unscoredRows = stats.level_counts.unscored ?? 0;

  return (
    <div>
      <div className="kicker">Republic of Moldova · public procurement</div>
      <h1>Corruption-risk radar</h1>
      <p className="lede">
        Four independent detectors — MAD z-score, Isolation Forest, Local Outlier Factor and
        One-Class SVM — score a flagged-candidate sample drawn from{" "}
        {stats.n_tenders.toLocaleString()} real procedures in the MTender feed. The priority band is
        set by how many of them agreed, so a band means corroboration rather than one model&apos;s
        opinion.
      </p>

      {unscoredRows > 0 && (
        <div className="callout warn">
          <strong>Coverage first.</strong> {int(unscoredRows)} of the {int(stats.n_tenders)}{" "}
          procedures here ({pct(unscoredRows / stats.n_tenders)}) have <em>no</em> detector output —
          the detection run scored {int(scoredRows)} of them. Those records are shown as{" "}
          <strong>not scored</strong>, never as &quot;low risk&quot;: no model examined them, so
          nothing clears them. Every figure below that describes model behaviour is a share of the{" "}
          {int(scoredRows)} scored records only.
        </div>
      )}

      <div className="grid cards-4">
        <Stat
          label="Procedures scored"
          value={int(scoredRows)}
          note={`of ${int(stats.n_tenders)} in the corpus`}
        />
        <Stat
          label="High / critical"
          value={int(stats.high_risk_count)}
          note={
            scoredRows > 0
              ? `${pct(stats.high_risk_count / scoredRows)} of scored records`
              : "no scored records"
          }
          tone={stats.high_risk_count > 0 ? "high" : undefined}
        />
        <Stat
          label="Value in the high-risk set"
          value={mdl(stats.high_risk_value_mdl)}
          note="Sum of all awarded lots"
        />
        <Stat
          label="Single-bidder share"
          value={stats.single_bidder_share === null ? "—" : pct(stats.single_bidder_share)}
          note={
            hasNoPublishedBids
              ? "No procedure published a participant list"
              : `of ${int(stats.n_with_bid_data)} with a published bidder list`
          }
        />
      </div>

      <div className="grid row2">
        <div className="card">
          <h2>Mean anomaly percentile by month</h2>
          <p className="muted">
            Rank of each procedure's most extreme detector within this dataset, averaged per month.
            Not a probability, and not comparable across pipeline runs.
          </p>
          {months.length === 0 ? (
            <Empty title="No dated procedures" hint="The export contains no usable dates." />
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={months} margin={{ top: 6, right: 8, bottom: 4, left: -18 }}>
                <CartesianGrid stroke="#eee6d8" vertical={false} />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: "#5c6673" }}
                  tickLine={false}
                  axisLine={{ stroke: "#d9d0c0" }}
                  minTickGap={24}
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fontSize: 11, fill: "#5c6673" }}
                  tickLine={false}
                  axisLine={false}
                  width={44}
                />
                <Tooltip
                  formatter={(v: number | string) => [num1(Number(v)), "mean percentile"]}
                  labelFormatter={(l) => String(l)}
                />
                <Line
                  type="monotone"
                  dataKey="avg_risk"
                  stroke="#1e3a5f"
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        <div className="card">
          <h2>Priority bands</h2>
          <p className="muted">
            By number of detectors that flagged the procedure: 0 low, 1 medium, 2 high, 3 or more
            critical.
          </p>
          {bandData.length === 0 ? (
            <Empty title="No banded procedures" />
          ) : (
            <ResponsiveContainer width="100%" height={244}>
              <BarChart data={bandData} margin={{ top: 6, right: 8, bottom: 4, left: -18 }}>
                <CartesianGrid stroke="#eee6d8" vertical={false} />
                <XAxis
                  dataKey="level"
                  tick={{ fontSize: 11, fill: "#5c6673" }}
                  tickLine={false}
                  axisLine={{ stroke: "#d9d0c0" }}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "#5c6673" }}
                  tickLine={false}
                  axisLine={false}
                  width={44}
                />
                <Tooltip formatter={(v: number | string) => [num(Number(v)), "procedures"]} />
                <Bar dataKey="n" radius={[6, 6, 0, 0]}>
                  {/* Same colours as the band badges, so the chart and the
                      table read as one system. */}
                  {bandData.map((d) => (
                    <Cell key={d.level} fill={BAND_FILL[d.level]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
          <ul className="legend">
            {bandData.map((d) => (
              <li key={d.level}>
                <span className="swatch" style={{ background: BAND_FILL[d.level] }} />
                {d.level} · {d.n}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="grid row2">
        <div className="card">
          <h2>Most frequent CPV groups</h2>
          <p className="muted">
            MTender publishes CPV codes without a label dictionary, so codes are shown as-is.
          </p>
          {stats.top_cpv.length === 0 ? (
            <Empty title="No CPV codes extracted" />
          ) : (
            <TableWrap>
              <table>
                <thead>
                  <tr>
                    <th scope="col">CPV code</th>
                    <th scope="col">Procedures</th>
                    <th scope="col">Mean percentile</th>
                    <th scope="col">Award value</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.top_cpv.map((r) => (
                    <tr key={r.cpv_code}>
                      <td className="mono">{r.cpv_code}</td>
                      <td className="mono">{num(r.n)}</td>
                      <td className="mono">{val(r.avg_risk, 1)}</td>
                      <td className="mono">{mdl(r.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </div>
        <div className="card">
          <h2>Model validation</h2>
          {m.available ? (
            <p className="muted">{m.reason}</p>
          ) : (
            <>
              <p className="muted">
                Precision, recall and F1 are <strong>not computable here</strong>: {m.reason}.
                Publishing them would mean inventing labels.
              </p>
              <p className="muted">
                Model quality is instead evidenced by agreement between four independent detectors
                and by univariate significance testing of each indicator against the consensus flag.
              </p>
            </>
          )}

          <h3 style={{ marginTop: 18 }}>Data source</h3>
          {loading ? (
            <Skeleton rows={3} />
          ) : mongo?.connected ? (
            <dl className="kv">
              <dt>MongoDB</dt>
              <dd className="mono">
                {mongo.uri} · {mongo.database}
              </dd>
              <dt>Replica set</dt>
              <dd className="mono">
                {mongo.set_name ?? "standalone"}{" "}
                {mongo.transactions ? "(transactions available)" : "(no transaction support)"}
              </dd>
              <dt>Procedures scored</dt>
              <dd className="mono">{int(meta?.scored ?? 0)}</dd>
            </dl>
          ) : (
            <p className="muted">MongoDB status unavailable: {mongo?.error ?? "not reported"}</p>
          )}

          {meta && Object.keys(meta.unavailable).length > 0 && (
            <>
              <h3 style={{ marginTop: 18 }}>Not published by MTender</h3>
              <ul className="muted" style={{ paddingLeft: 18, marginTop: 0 }}>
                {Object.entries(meta.unavailable).map(([k, why]) => (
                  <li key={k}>
                    <code>{k}</code> — {why}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
