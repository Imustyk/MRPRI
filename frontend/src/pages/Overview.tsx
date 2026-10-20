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
import { Trans, useTranslation } from "react-i18next";
import {
  dateLabel,
  getDataset,
  getJson,
  int,
  mdl,
  monthLabel,
  num,
  num1,
  pct,
  val,
  type DatasetReport,
  type Health,
  type Meta,
  type MongoStatus,
  type RiskLevel,
  type Stats,
} from "../api";
import { Empty, ErrorNote, PageHead, Pill, Skeleton, Stat, TableWrap } from "../ui";
import { tr } from "../i18n/backendMap";

const BAND_ORDER: RiskLevel[] = ["critical", "high", "medium", "low", "unscored"];
const BAND_FILL: Record<string, string> = {
  critical: "#b4232c",
  high: "#c2661f",
  medium: "#c9a02e",
  low: "#2a6b4a",
  unscored: "#c3c8cf",
};

export default function Overview() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<Stats | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [mongo, setMongo] = useState<MongoStatus | null>(null);
  const [dataset, setDataset] = useState<DatasetReport | null>(null);
  const [datasetErr, setDatasetErr] = useState<string | null>(null);
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
    // Provenance is advisory: a failure here degrades to an inline note, the
    // way the MongoDB source panel does, and never blocks the overview.
    // verify_hash recomputes SHA-256 once per server run (cached afterwards);
    // the provenance card can then show the verified state instead of
    // "verification not requested".
    getDataset(true)
      .then(setDataset)
      .catch((e: Error) => setDatasetErr(e.message));
  };

  useEffect(() => {
    load();
  }, []);

  if (error && !stats) {
    return (
      <div>
        <div className="kicker">{t("overview.err_kicker")}</div>
        <h1>{t("overview.err_title")}</h1>
        <p className="lede">
          <Trans i18nKey="overview.err_lede" components={{ code: <code /> }} />
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
        <div className="kicker">{t("overview.load_kicker")}</div>
        <h1>{t("overview.load_title")}</h1>
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
      <PageHead
        kicker={t("overview.kicker")}
        title={t("overview.title")}
        lede={t("overview.lede", { n: stats.n_tenders.toLocaleString() })}
      />

      {unscoredRows > 0 && (
        <div className="callout warn">
          <Trans
            i18nKey="overview.coverage"
            values={{
              unscored: int(unscoredRows),
              total: int(stats.n_tenders),
              share: pct(unscoredRows / stats.n_tenders),
              scored: int(scoredRows),
            }}
            components={{ em: <em />, strong: <strong /> }}
          />
        </div>
      )}

      <div className="grid cards-4">
        <Stat
          label={t("overview.stat_scored")}
          value={int(scoredRows)}
          note={t("overview.stat_scored_note", { n: int(stats.n_tenders) })}
        />
        <Stat
          label={t("overview.stat_high")}
          value={int(stats.high_risk_count)}
          note={
            scoredRows > 0
              ? t("overview.stat_high_note", { share: pct(stats.high_risk_count / scoredRows) })
              : t("overview.stat_high_none")
          }
          tone={stats.high_risk_count > 0 ? "high" : undefined}
        />
        <Stat
          label={t("overview.stat_value")}
          value={mdl(stats.high_risk_value_mdl)}
          note={t("overview.stat_value_note")}
        />
        <Stat
          label={t("overview.stat_single")}
          value={stats.single_bidder_share === null ? "—" : pct(stats.single_bidder_share)}
          note={
            hasNoPublishedBids
              ? t("overview.stat_single_none")
              : t("overview.stat_single_note", { n: int(stats.n_with_bid_data) })
          }
        />
      </div>

      {/* Provenance: where the rows came from and how the run is traceable. */}
      <div className="card" style={{ marginTop: 16 }}>
        <h2>{t("overview.prov_h")}</h2>
        <p className="muted">{t("overview.prov_p")}</p>
        {datasetErr ? (
          <p className="muted">
            {t("overview.prov_error")} <span className="mono">{datasetErr}</span>
          </p>
        ) : !dataset ? (
          <Skeleton rows={3} />
        ) : (
          <>
            <div className="flags">
              <Pill
                tone={
                  dataset.origin.synthetic_in_use
                    ? "risk"
                    : dataset.origin.kind === "real-ocds"
                      ? "ok"
                      : dataset.origin.kind === "missing"
                        ? "warn"
                        : "muted"
                }
              >
                {dataset.origin.synthetic_in_use
                  ? t("overview.prov_synthetic")
                  : dataset.origin.kind === "real-ocds"
                    ? t("overview.prov_real")
                    : dataset.origin.kind === "missing"
                      ? t("overview.prov_missing")
                      : t("overview.prov_unknown")}
              </Pill>
            </div>
            <dl className="kv">
              <dt>{t("overview.prov_model")}</dt>
              <dd>
                <strong className="mono">{dataset.model.version}</strong>{" "}
                <span className="muted">{tr(dataset.model.label)}</span>
              </dd>
              <dt>{t("overview.prov_scoring")}</dt>
              <dd className="mono">
                {dataset.scoring.run_id ?? "—"} · {dateLabel(dataset.scoring.generated_at)}
              </dd>
              <dt>{t("overview.prov_corpus")}</dt>
              <dd className="mono">
                {t("overview.prov_corpus_line", {
                  records: int(dataset.corpus.records),
                  scored: int(dataset.corpus.scored),
                  unscored: int(dataset.corpus.unscored),
                })}
              </dd>
              <dt>{t("overview.prov_years")}</dt>
              <dd className="mono">
                {dataset.corpus.year_from ?? "—"}–{dataset.corpus.year_to ?? "—"}
              </dd>
              <dt>{t("overview.prov_manifest")}</dt>
              <dd className="mono">
                {t("overview.prov_manifest_line", {
                  date: dateLabel(dataset.manifest.exported_at),
                  n: int(dataset.manifest.n_documents),
                })}
                {dataset.verification.hash_matches_manifest === true ? (
                  <span className="muted"> · {t("overview.prov_hash_ok")}</span>
                ) : dataset.verification.hash_matches_manifest === false ? (
                  <span className="muted">
                    {" "}
                    ·{" "}
                    {t("overview.prov_hash_mismatch", {
                      n: int(dataset.verification.mismatches.length),
                    })}
                  </span>
                ) : (
                  <span className="muted"> · {t("overview.prov_hash_pending")}</span>
                )}
              </dd>
            </dl>
          </>
        )}
      </div>

      <div className="grid row2">
        <div className="card">
          <h2>{t("overview.monthly_h")}</h2>
          <p className="muted">
            <Trans i18nKey="overview.monthly_p" />
          </p>
          {months.length === 0 ? (
            <Empty title={t("overview.monthly_empty")} hint={t("overview.monthly_empty_hint")} />
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
                  formatter={(v: number | string) => [
                    num1(Number(v)),
                    t("overview.monthly_mean"),
                  ]}
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
          <h2>{t("overview.bands_h")}</h2>
          <p className="muted">{t("overview.bands_p")}</p>
          {bandData.length === 0 ? (
            <Empty title={t("overview.bands_empty")} />
          ) : (
            <ResponsiveContainer width="100%" height={244}>
              <BarChart data={bandData} margin={{ top: 6, right: 8, bottom: 4, left: -18 }}>
                <CartesianGrid stroke="#eee6d8" vertical={false} />
                <XAxis
                  dataKey="level"
                  tick={{ fontSize: 11, fill: "#5c6673" }}
                  tickLine={false}
                  axisLine={{ stroke: "#d9d0c0" }}
                  tickFormatter={(v: string) => t(`risk.${v}`)}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "#5c6673" }}
                  tickLine={false}
                  axisLine={false}
                  width={44}
                />
                <Tooltip
                  formatter={(v: number | string) => [num(Number(v)), t("overview.bands_procedures")]}
                  labelFormatter={(l) => t(`risk.${l}`)}
                />
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
                {t(`risk.${d.level}`)} · {d.n}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="grid row2">
        <div className="card">
          <h2>{t("overview.cpv_h")}</h2>
          <p className="muted">{t("overview.cpv_p")}</p>
          {stats.top_cpv.length === 0 ? (
            <Empty title={t("overview.cpv_empty")} />
          ) : (
            <TableWrap>
              <table>
                <thead>
                  <tr>
                    <th scope="col">{t("overview.cpv_th_code")}</th>
                    <th scope="col">{t("overview.cpv_th_procedures")}</th>
                    <th scope="col">{t("overview.cpv_th_mean")}</th>
                    <th scope="col">{t("overview.cpv_th_value")}</th>
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
          <h2>{t("overview.valid_h")}</h2>
          {m.available ? (
            <p className="muted">{tr(m.reason)}</p>
          ) : (
            <>
              <p className="muted">
                <Trans i18nKey="overview.valid_p" values={{ reason: tr(m.reason) }} components={{ strong: <strong /> }} />
              </p>
              <p className="muted">
                <Trans i18nKey="overview.valid_p2" />
              </p>
            </>
          )}

          <h3 style={{ marginTop: 18 }}>{t("overview.source_h")}</h3>
          {loading ? (
            <Skeleton rows={3} />
          ) : mongo?.connected ? (
            <dl className="kv">
              <dt>{t("overview.kv_mongodb")}</dt>
              <dd className="mono">
                {mongo.uri} · {mongo.database}
              </dd>
              <dt>{t("overview.kv_replica")}</dt>
              <dd className="mono">
                {mongo.set_name ?? t("overview.kv_standalone")}{" "}
                {mongo.transactions
                  ? t("overview.kv_tx_yes")
                  : t("overview.kv_tx_no")}
              </dd>
              <dt>{t("overview.kv_scored")}</dt>
              <dd className="mono">{int(meta?.scored ?? 0)}</dd>
            </dl>
          ) : (
            <p className="muted">
              {t("overview.mongo_unavail", { err: mongo?.error ?? t("overview.mongo_not_reported") })}
            </p>
          )}

          {meta && Object.keys(meta.unavailable).length > 0 && (
            <>
              <h3 style={{ marginTop: 18 }}>{t("overview.not_pub_h")}</h3>
              <ul className="muted" style={{ paddingLeft: 18, marginTop: 0 }}>
                {Object.entries(meta.unavailable).map(([k, why]) => (
                  <li key={k}>
                    <code>{k}</code> — {tr(why)}
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
