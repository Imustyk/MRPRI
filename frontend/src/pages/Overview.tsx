import { useRequest } from "../hooks";
import { Link } from "react-router-dom";
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
  type Health,
  type Meta,
  type RiskLevel,
  type Stats,
} from "../api";
import { Empty, ErrorNote, PageHead, Pill, Skeleton, Stat, TableWrap } from "../ui";
import { tr } from "../i18n/backendMap";

const BAND_ORDER: RiskLevel[] = ["critical", "high", "medium", "low", "unscored"];
const BAND_FILL: Record<string, string> = {
  critical: "var(--band-critical)",
  high: "var(--band-high)",
  medium: "var(--band-medium)",
  low: "var(--band-low)",
  unscored: "var(--band-unscored)",
};

export default function Overview() {
  const { t } = useTranslation();
  const statsReq = useRequest("stats", signal => getJson<Stats>("/api/stats", signal));
  const metaReq = useRequest("meta", signal => getJson<Meta>("/api/meta", signal));
  const healthReq = useRequest("health", signal => getJson<Health>("/api/health", signal));
  const datasetReq = useRequest("dataset", signal => getDataset(true, signal));
  const stats = statsReq.error ? null : statsReq.data;
  const meta = metaReq.error ? null : metaReq.data;
  const mongo = healthReq.error ? null : healthReq.data?.mongodb;
  const dataset = datasetReq.error ? null : datasetReq.data;
  const datasetErr = datasetReq.error;
  const error = statsReq.error;
  const load = statsReq.reload;
  const header = <PageHead title={t("product.homeTitle")} lede={t("product.homeLede")} actions={<>
    <Link className="action-primary" to="/tenders">{t("product.browse")}</Link>
    <Link className="action-secondary" to="/models">{t("product.results")}</Link>
    <Link className="action-secondary" to="/method">{t("product.how")}</Link>
  </>} />;
  if (!stats) return <div className="overview-page">
    {header}
    {error ? <ErrorNote error={error} onRetry={load} /> : <Skeleton rows={5} height={44} />}
  </div>;

  const m = stats.metrics;
  const bandData = BAND_ORDER.filter((b) => stats.level_counts[b]).map((b) => ({
    level: b,
    n: stats.level_counts[b],
  }));
  const cohorts = stats.snapshot_cohorts;
  const months = (cohorts?.monthly ?? []).map((r) => ({ ...r, label: monthLabel(r.month) }));
  const hasNoPublishedBids = stats.n_with_bid_data === 0;
  // Shares of model outcomes use the scored population as their denominator.
  const scoredRows = bandData.filter((b) => b.level !== "unscored").reduce((a, b) => a + b.n, 0);
  const unscoredRows = stats.level_counts.unscored ?? 0;

  return (
    <div className="overview-page">
      {header}
      {dataset && <p className="microcopy">
        {t("product.source")} · {t(dataset.origin.kind === "real-ocds" ? "overview.prov_real" : dataset.origin.synthetic_in_use ? "overview.prov_synthetic" : "overview.prov_unknown")} · {dateLabel(dataset.manifest.exported_at)}
      </p>}

      {metaReq.error && <ErrorNote error={metaReq.error} onRetry={metaReq.reload} />}
      {healthReq.error && <ErrorNote error={healthReq.error} onRetry={healthReq.reload} />}
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
        <Stat label={t("product.corpus")} value={int(stats.n_tenders)} />
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

      <ul className="legend" aria-label={t("overview.bands_h")}>
        {BAND_ORDER.map(level => <li key={level}>
          <span className="swatch" style={{ background: BAND_FILL[level] }} />
          <Link to={`/tenders?level=${level}`}>{t(`risk.${level}`)} · {int(stats.level_counts[level] ?? 0)}</Link>
        </li>)}
      </ul>

      {/* Provenance: where the rows came from and how the run is traceable. */}
      <details className="card provenance-disclosure" open={datasetErr !== null || dataset?.origin.synthetic_in_use === true || dataset?.verification.hash_matches_manifest === false}>
        <summary>{t("overview.prov_h")}</summary>
        <p className="muted">{t("overview.prov_p")}</p>
        {datasetErr ? (
          <ErrorNote error={datasetErr} onRetry={datasetReq.reload} />
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
      </details>

      <div className="grid row2">
        <div className="card">
          <h2>{t("overview.monthly_h")}</h2>
          <p className="muted">
            <Trans i18nKey="overview.monthly_p" />
          </p>
          {months.length === 0 ? (
            <Empty title={t("overview.monthly_empty")} hint={t("overview.monthly_empty_hint")} />
          ) : (
            <>
              <div className="cohort-summary">
                <span>{t("overview.monthly_period", { from: months[0].label, to: months[months.length - 1].label })}</span>
                <span>{t("overview.monthly_coverage", { dated: int(cohorts!.n_dated), total: int(cohorts!.n_total), scored: int(cohorts!.n_scored) })}</span>
              </div>
              <h3 className="cohort-chart-title">{t("overview.monthly_mean")}</h3>
              {months.some((month) => month.n_scored > 0) ? (
                <div role="img" aria-label={t("overview.monthly_line_a11y")}>
                  <ResponsiveContainer width="100%" height={230}>
                    <LineChart data={months} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
                      <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 10, fill: "var(--muted)" }} tickLine={false} axisLine={false} minTickGap={30} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "var(--muted)" }} tickLine={false} axisLine={false} width={40} />
                      <Tooltip formatter={(value: number | string) => [num1(Number(value)), t("overview.monthly_mean")]} labelFormatter={(label) => String(label)} />
                      <Line type="linear" dataKey="avg_risk" stroke="var(--navy-soft)" strokeWidth={2} dot={false} activeDot={{ r: 4 }} connectNulls={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : <Empty title={t("overview.monthly_no_scores")} />}
              <h3 className="cohort-chart-title">{t("overview.monthly_volume")}</h3>
              <ul className="legend">
                <li><span className="cohort-dot scored" />{t("overview.monthly_scored")}</li>
                <li><span className="cohort-dot unscored" />{t("overview.monthly_unscored")}</li>
              </ul>
              <div role="img" aria-label={t("overview.monthly_bar_a11y")}>
                <ResponsiveContainer width="100%" height={150}>
                  <BarChart data={months} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 10, fill: "var(--muted)" }} tickLine={false} axisLine={false} minTickGap={30} />
                    <YAxis tick={{ fontSize: 10, fill: "var(--muted)" }} tickLine={false} axisLine={false} width={54} allowDecimals={false} />
                    <Tooltip formatter={(value: number | string, name: string) => [int(Number(value)), t(name === "n_scored" ? "overview.monthly_scored" : "overview.monthly_unscored")]} />
                    <Bar dataKey="n_scored" stackId="coverage" fill="var(--navy-soft)" isAnimationActive={false} />
                    <Bar dataKey="n_unscored" stackId="coverage" fill="var(--chart-neutral)" isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="cohort-source">{t("overview.monthly_source")}</p>
              <p className="cohort-source">{t("overview.monthly_excluded", { missing: int(cohorts!.n_missing_date), invalid: int(cohorts!.n_invalid_date) })}</p>
              <details className="cohort-values">
                <summary>{t("overview.monthly_table")}</summary>
                <TableWrap>
                  <table>
                    <caption className="visually-hidden">{t("overview.monthly_h")}</caption>
                    <thead><tr><th scope="col">{t("overview.monthly_month")}</th><th scope="col">{t("overview.monthly_volume")}</th><th scope="col">{t("overview.monthly_scored")}</th><th scope="col">{t("overview.monthly_mean")}</th></tr></thead>
                    <tbody>{months.map((month) => <tr key={month.month}><th scope="row">{month.label}</th><td>{int(month.n)}</td><td>{int(month.n_scored)}</td><td>{month.avg_risk === null ? "—" : num1(month.avg_risk)}</td></tr>)}</tbody>
                  </table>
                </TableWrap>
              </details>
            </>
          )}
        </div>
        <div className="card">
          <h2>{t("overview.bands_h")}</h2>
          <p className="muted">{t("overview.bands_p")}</p>
          {bandData.length === 0 ? (
            <Empty title={t("overview.bands_empty")} />
          ) : (
            <ResponsiveContainer width="100%" height={244}>
              <BarChart data={bandData} margin={{ top: 6, right: 8, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                <XAxis
                  dataKey="level"
                  tick={{ fontSize: 11, fill: "var(--muted)" }}
                  tickLine={false}
                  axisLine={{ stroke: "var(--line)" }}
                  minTickGap={12}
                  tickFormatter={(v: string) => t(`risk.${v}`)}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "var(--muted)" }}
                  tickLine={false}
                  axisLine={false}
                  width={60}
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
          {healthReq.loading ? (
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
              <dd className="mono">{int(meta?.scored)}</dd>
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
