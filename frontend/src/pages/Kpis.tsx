import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import {
  getModelKpis,
  int,
  type KpiCheck,
  type KpiDetector,
  type KpiStatus,
  type ModelKpis,
} from "../api";
import { ErrorNote, MiniStats, PageHead, Pill, Skeleton, TableWrap } from "../ui";
import { tr } from "../i18n/backendMap";

const STATUS_TONE: Record<KpiStatus, string> = { pass: "ok", fail: "risk", skip: "muted" };

/** Declared run parameters as one line: "n_estimators=300 · contamination=0.05". */
function paramsLine(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(" · ");
}

/** Observed share with the precision the run summary records, never more. */
function pct(n: number | null | undefined): string {
  return n === null || n === undefined ? "\u2014" : `${n.toFixed(3)}%`;
}

export default function Kpis() {
  const { t } = useTranslation();
  const [data, setData] = useState<ModelKpis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getModelKpis()
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  useEffect(load, [load]);

  const statusLabel = (s: KpiStatus) =>
    s === "pass" ? t("kpis.status_pass") : s === "fail" ? t("kpis.status_fail") : t("kpis.status_skip");

  if (loading && !data) {
    return (
      <div>
        <PageHead kicker={t("kpis.kicker")} title={t("kpis.title")} />
        <Skeleton rows={2} height={40} />
        <Skeleton rows={6} />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div>
        <PageHead kicker={t("kpis.kicker")} title={t("kpis.title")} />
        <ErrorNote error={error} onRetry={load} />
      </div>
    );
  }

  if (!data) return null;

  const passed = data.checks.filter((c) => c.status === "pass").length;
  const scoredChecks = data.n_checks - data.n_skipped;
  const labelOf = (key: string | null) =>
    (key && data.detectors.find((d: KpiDetector) => d.key === key)?.label &&
      tr(data.detectors.find((d: KpiDetector) => d.key === key)!.label)) ||
    t("kpis.whole_corpus");

  return (
    <div>
      <PageHead
        kicker={t("kpis.kicker")}
        title={t("kpis.title")}
        lede={
          <Trans i18nKey="kpis.lede" components={{ racilink: <Link to="/raci" /> }} />
        }
      />

      <div className={`callout ${data.ok ? "info" : "warn"}`}>
        <strong>
          {data.ok
            ? t("kpis.callout_ok")
            : t("kpis.callout_fail", { failed: data.n_failed, total: data.n_checks })}
        </strong>{" "}
        {t("kpis.callout_sub", {
          passed,
          scored: scoredChecks,
          skipped: data.n_skipped,
          rows: int(data.n_scored),
          served: int(data.n_rows),
        })}
      </div>

      <div className="callout warn">
        <strong>{t("kpis.metrics_warn")}</strong> {tr(data.metrics.reason)}
      </div>

      <MiniStats
        items={[
          {
            label: t("kpis.mini_passing"),
            value: `${passed}/${scoredChecks}`,
            tone: data.ok ? "ok" : "risk",
          },
          { label: t("kpis.mini_rows"), value: int(data.n_scored), tone: "ok" },
          {
            label: t("kpis.mini_contam"),
            value: `${(data.contamination.declared * 100).toFixed(0)}%`,
            tone: "warn",
          },
          {
            label: t("kpis.mini_tolerance"),
            value: `\u00b1${(data.contamination.tolerance * 100).toFixed(0)} pp`,
            tone: "muted",
          },
        ]}
      />

      <div className="card">
        <h2>{t("kpis.run_h")}</h2>
        {data.run ? (
          <dl className="kv">
            <dt>{t("kpis.run_label")}</dt>
            <dd className="mono">{data.run.run_id}</dd>
            <dt>{t("kpis.run_generated")}</dt>
            <dd className="mono">{data.run.generated_at}</dd>
            <dt>{t("kpis.run_rows")}</dt>
            <dd className="mono">{int(data.run.n_rows)}</dd>
            <dt>{t("kpis.run_contamination")}</dt>
            <dd className="mono">{data.run.contamination_assumption}</dd>
            <dt>{t("kpis.run_preprocessing")}</dt>
            <dd>{data.run.preprocessing}</dd>
            <dt>{t("kpis.run_source")}</dt>
            <dd className="mono">{data.run.source}</dd>
          </dl>
        ) : (
          <p className="muted">
            <Trans i18nKey="kpis.run_none" />
          </p>
        )}
      </div>

      <div className="card">
        <h2>{t("kpis.cat_h")}</h2>
        <p className="muted">
          <Trans i18nKey="kpis.cat_p" />
        </p>
        <TableWrap wide>
          <table>
            <thead>
              <tr>
                <th>{t("kpis.cat_th_detector")}</th>
                <th>{t("kpis.cat_th_family")}</th>
                <th>{t("kpis.cat_th_threshold")}</th>
                <th>{t("kpis.cat_th_params")}</th>
                <th>{t("kpis.cat_th_artifact")}</th>
                <th>{t("kpis.cat_th_flagged")}</th>
                <th>{t("kpis.cat_th_recorded")}</th>
              </tr>
            </thead>
            <tbody>
              {data.detectors.map((d) => (
                <tr key={d.key}>
                  <td>
                    <strong>{tr(d.label)}</strong>
                    <div className="muted mono">{d.score_field}</div>
                  </td>
                  <td className="muted">{tr(d.family)}</td>
                  <td className="mono">
                    {d.threshold.name}={d.threshold.value}
                    {d.threshold.kind === "contamination"
                      ? ` \u00b1${(data.contamination.tolerance * 100).toFixed(0)} pp`
                      : ""}
                  </td>
                  <td className="muted">{paramsLine(d.params)}</td>
                  <td>
                    {d.artifact.path ? (
                      <span className="mono">
                        {d.artifact.path}{" "}
                        <Pill tone={STATUS_TONE[d.artifact.status]}>
                          {statusLabel(d.artifact.status)}
                        </Pill>
                      </span>
                    ) : (
                      <span className="muted">{d.artifact.note}</span>
                    )}
                  </td>
                  <td className="mono">
                    {pct(d.live.pct_flagged)} &middot; {int(d.live.n_flagged)} {t("common.of")}{" "}
                    {int(d.live.n_scored)}
                  </td>
                  <td className="mono">
                    {d.run_recorded && d.run_recorded.pct_flagged !== null
                      ? `${pct(d.run_recorded.pct_flagged)} \u00b7 ${int(d.run_recorded.n_flagged)}`
                      : "\u2014"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </div>

      <div className="card">
        <h2>{t("kpis.checks_h")}</h2>
        <p className="muted">
          <Trans i18nKey="kpis.checks_p" />
        </p>
        <TableWrap wide>
          <table>
            <thead>
              <tr>
                <th>{t("kpis.checks_th_status")}</th>
                <th>{t("kpis.checks_th_check")}</th>
                <th>{t("kpis.checks_th_scope")}</th>
                <th>{t("kpis.checks_th_detail")}</th>
              </tr>
            </thead>
            <tbody>
              {data.checks.map((c: KpiCheck) => (
                <tr key={c.id}>
                  <td>
                    <Pill tone={STATUS_TONE[c.status]}>{statusLabel(c.status)}</Pill>
                  </td>
                  <td>{tr(c.label)}</td>
                  <td className="muted">{labelOf(c.detector)}</td>
                  <td className="mono">{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      </div>
    </div>
  );
}
