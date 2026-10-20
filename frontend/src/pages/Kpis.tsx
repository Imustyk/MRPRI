import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import {
  getEvaluation,
  getExplainability,
  getModelKpis,
  int,
  val,
  type Evaluation,
  type Explainability,
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

/** Corpus share as a percentage (0.050283 -> "5.03%"), null-safe. */
function share(n: number | null | undefined, digits = 3): string {
  return n === null || n === undefined || Number.isNaN(n)
    ? "\u2014"
    : `${(n * 100).toFixed(digits)}%`;
}

/** AUC-style figure: three decimals, never more than the artefact records. */
function auc3(n: number | null | undefined): string {
  return n === null || n === undefined || Number.isNaN(n) ? "\u2014" : n.toFixed(3);
}

/** Artefact figures may arrive as strings; unusable values render as "—". */
function fig(v: number | string | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export default function Kpis() {
  const { t } = useTranslation();
  const [data, setData] = useState<ModelKpis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [evalErr, setEvalErr] = useState<string | null>(null);
  const [evalLoading, setEvalLoading] = useState(true);
  const [xai, setXai] = useState<Explainability | null>(null);
  const [xaiErr, setXaiErr] = useState<string | null>(null);
  const [xaiLoading, setXaiLoading] = useState(true);

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
    // The research panels are advisory: each carries its own loading/error
    // state so a missing artefact degrades to a note, not a blank page.
    setEvalLoading(true);
    setEvalErr(null);
    getEvaluation()
      .then((d) => {
        setEvaluation(d);
        setEvalLoading(false);
      })
      .catch((e: Error) => {
        setEvalErr(e.message);
        setEvalLoading(false);
      });
    setXaiLoading(true);
    setXaiErr(null);
    getExplainability()
      .then((d) => {
        setXai(d);
        setXaiLoading(false);
      })
      .catch((e: Error) => {
        setXaiErr(e.message);
        setXaiLoading(false);
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

  // Explainability figures, computed once for the consistency card below.
  const sp = xai?.xai_consistency.agreement.spearman;
  const spCi = sp?.mean_ci;
  const permTop = [...(xai?.permutation_importance ?? [])]
    .sort((a, b) => (fig(b.mean) ?? -Infinity) - (fig(a.mean) ?? -Infinity))
    .slice(0, 5);
  const shapTop = [...(xai?.shap_importance ?? [])]
    .sort((a, b) => (fig(b.mean_abs) ?? -Infinity) - (fig(a.mean_abs) ?? -Infinity))
    .slice(0, 5);

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

      {/* Independent evidence: proxy labels, seed/noise stability, drift and
          the bias audit — every negative result rendered exactly as measured. */}
      <div className="card" style={{ marginTop: 16 }}>
        <h2>{t("kpis.evidence_h")}</h2>
        <p className="muted">{t("kpis.evidence_p")}</p>

        {evalLoading ? (
          <Skeleton rows={6} />
        ) : evalErr ? (
          <ErrorNote error={evalErr} onRetry={load} />
        ) : !evaluation ? (
          <p className="muted">{t("kpis.ext_na")}</p>
        ) : (
          <>
            <h3 style={{ marginTop: 14 }}>{t("kpis.ext_h")}</h3>
            <p className="muted">{t("kpis.ext_p")}</p>
            {evaluation.external_labels.map((lb) => {
              const ci = lb.cluster_ci ?? null;
              const spansHalf = ci ? ci[0] <= 0.5 && ci[1] >= 0.5 : false;
              const atOrBelowRandom =
                lb.roc_auc !== null && lb.roc_auc !== undefined && lb.roc_auc <= 0.5;
              return (
                <div key={lb.id} style={{ marginTop: 12 }}>
                  <p style={{ margin: 0 }}>
                    <strong>{tr(lb.label)}</strong>
                  </p>
                  {!lb.available || lb.roc_auc === null || lb.roc_auc === undefined ? (
                    <p className="muted">{t("kpis.ext_na")}</p>
                  ) : (
                    <>
                      <dl className="kv">
                        <dt>{t("kpis.ext_auc")}</dt>
                        <dd className="mono">
                          {auc3(lb.roc_auc)}
                          {ci && (
                            <>
                              {" · "}
                              {t("kpis.ext_ci", { low: auc3(ci[0]), high: auc3(ci[1]) })}
                            </>
                          )}
                        </dd>
                        {lb.base_rate !== null && lb.base_rate !== undefined && (
                          <>
                            <dt>{t("kpis.ext_base_rate")}</dt>
                            <dd className="mono">{share(lb.base_rate)}</dd>
                          </>
                        )}
                        {lb.pr_auc !== null && lb.pr_auc !== undefined && (
                          <>
                            <dt>{t("kpis.ext_pr_auc")}</dt>
                            <dd className="mono">{auc3(lb.pr_auc)}</dd>
                          </>
                        )}
                        {lb.precision_votes_ge3 !== null &&
                          lb.precision_votes_ge3 !== undefined && (
                            <>
                              <dt>{t("kpis.ext_precision")}</dt>
                              <dd className="mono">{share(lb.precision_votes_ge3)}</dd>
                            </>
                          )}
                        {lb.n_clusters !== null && lb.n_clusters !== undefined &&
                          lb.n_boot !== null && lb.n_boot !== undefined && (
                            <>
                              <dt>{t("kpis.ext_cluster_meta")}</dt>
                              <dd className="mono">
                                {t("kpis.ext_cluster_val", {
                                  clusters: int(lb.n_clusters),
                                  boot: int(lb.n_boot),
                                })}
                              </dd>
                            </>
                          )}
                      </dl>
                      {(atOrBelowRandom || spansHalf) && (
                        <div className="flags" style={{ marginTop: 6 }}>
                          {atOrBelowRandom && <Pill tone="risk">{t("kpis.ext_random")}</Pill>}
                          {spansHalf && <Pill tone="risk">{t("kpis.ext_ci_half")}</Pill>}
                        </div>
                      )}
                      {lb.verdict_text && (
                        <p className="muted" style={{ margin: "6px 0 0" }}>
                          {lb.verdict_code && <span className="mono">{lb.verdict_code}</span>}
                          {lb.verdict_code && " — "}
                          {tr(lb.verdict_text)}
                        </p>
                      )}
                    </>
                  )}
                  <p className="muted" style={{ marginTop: 6 }}>
                    {tr(lb.caveat)}
                  </p>
                </div>
              );
            })}

            <h3 style={{ marginTop: 18 }}>{t("kpis.seed_h")}</h3>
            <p className="muted">{t("kpis.seed_p")}</p>
            {evaluation.seed_stability ? (
              <dl className="kv">
                <dt>{t("kpis.seed_runs")}</dt>
                <dd className="mono">{int(evaluation.seed_stability.runs)}</dd>
                <dt>{t("kpis.seed_jaccard")}</dt>
                <dd className="mono">{val(evaluation.seed_stability.jaccard_mean, 4)}</dd>
                <dt>{t("kpis.seed_consensus")}</dt>
                <dd className="mono">{val(evaluation.seed_stability.consensus_mean, 1)}</dd>
              </dl>
            ) : (
              <p className="muted">{t("kpis.ext_na")}</p>
            )}

            <h3 style={{ marginTop: 18 }}>{t("kpis.noise_h")}</h3>
            <p className="muted">{t("kpis.noise_p")}</p>
            {evaluation.noise_sensitivity.verdicts && (
              <div className="flags" style={{ marginTop: 8 }}>
                {Object.entries(evaluation.noise_sensitivity.verdicts).map(([vid, v]) => {
                  const tone = v.passed === false ? "risk" : v.passed === true ? "ok" : "muted";
                  const status =
                    v.passed === false
                      ? t("kpis.hyp_failed")
                      : v.passed === true
                        ? t("kpis.hyp_passed")
                        : t("kpis.hyp_measured");
                  // Numeric detail stays in the tooltip, unrounded in the source
                  // and rounded for display only.
                  const detail = Object.entries(v)
                    .filter(([k]) => k !== "passed" && k !== "note")
                    .map(([k, raw]) =>
                      typeof raw === "number" ? `${k}=${Number(raw.toFixed(4))}` : `${k}=${String(raw)}`,
                    )
                    .join(" · ");
                  return (
                    <span key={vid} title={detail}>
                      <Pill tone={tone}>
                        <span className="mono">{vid}</span> · {status}
                      </Pill>
                    </span>
                  );
                })}
              </div>
            )}
            {evaluation.noise_sensitivity.regimes.length === 0 ? (
              <p className="muted">{t("kpis.noise_empty")}</p>
            ) : (
              <TableWrap wide>
                <table>
                  <thead>
                    <tr>
                      <th scope="col">{t("kpis.noise_th_regime")}</th>
                      <th scope="col">{t("kpis.noise_th_spearman")}</th>
                      <th scope="col">{t("kpis.noise_th_band")}</th>
                      <th scope="col">{t("kpis.noise_th_jaccard")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluation.noise_sensitivity.regimes.map((r) => (
                      <tr key={r.id}>
                        <td className="mono">{r.id}</td>
                        <td className="mono">
                          {val(r.spearman, 3)}
                          {r.spearman_ci_low !== null &&
                            r.spearman_ci_low !== undefined &&
                            r.spearman_ci_high !== null &&
                            r.spearman_ci_high !== undefined && (
                              <span className="muted" style={{ marginLeft: 6, fontSize: 12 }}>
                                {t("kpis.ext_ci", {
                                  low: val(r.spearman_ci_low, 3),
                                  high: val(r.spearman_ci_high, 3),
                                })}
                              </span>
                            )}
                        </td>
                        <td className="mono">
                          {r.band_change_pct === null || r.band_change_pct === undefined
                            ? "\u2014"
                            : `${val(r.band_change_pct, 1)}%`}
                        </td>
                        <td className="mono">{val(r.top200_jaccard, 3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            )}
            <p className="muted" style={{ marginTop: 8 }}>
              {tr(evaluation.noise_sensitivity.note)}
            </p>

            <h3 style={{ marginTop: 18 }}>{t("kpis.drift_h")}</h3>
            <dl className="kv">
              <dt>{t("kpis.drift_psi")}</dt>
              <dd className="mono">{val(evaluation.drift.psi_max, 3)}</dd>
              <dt>{t("kpis.drift_ks")}</dt>
              <dd className="mono">{val(evaluation.drift.ks_max, 3)}</dd>
            </dl>
            <p className="muted">{tr(evaluation.drift.note)}</p>
            <p className="muted">
              {evaluation.drift.overfitting_warning
                ? t("kpis.drift_overfit")
                : t("kpis.drift_no_overfit")}
            </p>

            <h3 style={{ marginTop: 18 }}>{t("kpis.bias_h")}</h3>
            {!evaluation.bias.available ? (
              <p className="muted">{t("kpis.ext_na")}</p>
            ) : (
              <>
                <dl className="kv">
                  <dt>{t("kpis.bias_dims")}</dt>
                  <dd className="mono">{int(evaluation.bias.n_dimensions)}</dd>
                  <dt>{t("kpis.bias_high_share")}</dt>
                  <dd className="mono">{share(evaluation.bias.high_plus_share_corpus, 2)}</dd>
                  <dt>{t("kpis.bias_critical_share")}</dt>
                  <dd className="mono">{share(evaluation.bias.critical_share_corpus, 2)}</dd>
                </dl>
                {evaluation.bias.verdict_counts && (
                  <p className="muted" style={{ marginTop: 8 }}>
                    {t("kpis.bias_verdicts")}:{" "}
                    {Object.entries(evaluation.bias.verdict_counts).map(([k, n], i) => (
                      <span key={k}>
                        {i > 0 ? " · " : ""}
                        {tr(k)} — <span className="mono">{n}</span>
                      </span>
                    ))}
                  </p>
                )}
              </>
            )}
          </>
        )}

        <div className="callout warn" style={{ marginBottom: 0 }}>
          {t("kpis.evidence_disclaimer")}
        </div>
      </div>

      {/* SHAP vs LIME agreement, reported as measured — a negative result. */}
      <div className="card" style={{ marginTop: 16 }}>
        <h2>{t("kpis.xai_h")}</h2>
        <p className="muted">{t("kpis.xai_p")}</p>
        {xaiLoading ? (
          <Skeleton rows={5} />
        ) : xaiErr ? (
          <ErrorNote error={xaiErr} onRetry={load} />
        ) : !xai ? (
          <p className="muted">{t("kpis.xai_na")}</p>
        ) : !xai.xai_consistency.available ? (
          <p className="muted">{t("kpis.xai_na")}</p>
        ) : (
          <>
            <div className="callout warn">
              <strong>
                {t("kpis.xai_verdict")}: {tr(xai.xai_consistency.verdict)}
              </strong>{" "}
              {sp &&
                sp.mean !== null &&
                sp.mean !== undefined &&
                t("kpis.xai_spearman", {
                  mean: val(sp.mean, 3),
                  low: val(spCi ? spCi[0] : null, 3),
                  high: val(spCi ? spCi[1] : null, 3),
                })}
            </div>

            <div className="grid row2">
              <div>
                <h3>{t("kpis.xai_perm_h")}</h3>
                <p className="muted">{t("kpis.xai_top5", { n: int(xai.permutation_importance.length) })}</p>
                <TableWrap>
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">{t("kpis.xai_feature")}</th>
                        <th scope="col">{t("kpis.xai_mean")}</th>
                        <th scope="col">{t("kpis.xai_std")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {permTop.map((r) => (
                        <tr key={r.feature}>
                          <td className="mono">{r.feature}</td>
                          <td className="mono">{val(fig(r.mean), 4)}</td>
                          <td className="mono">{val(fig(r.std), 4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              </div>
              <div>
                <h3>{t("kpis.xai_shap_h")}</h3>
                <p className="muted">{t("kpis.xai_top5", { n: int(xai.shap_importance.length) })}</p>
                <TableWrap>
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">{t("kpis.xai_feature")}</th>
                        <th scope="col">{t("kpis.xai_mean_abs")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shapTop.map((r) => (
                        <tr key={r.feature}>
                          <td className="mono">{r.feature}</td>
                          <td className="mono">{val(fig(r.mean_abs), 4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              </div>
            </div>

            <h3 style={{ marginTop: 16 }}>{t("kpis.xai_notes_h")}</h3>
            <ul className="muted" style={{ paddingLeft: 18, marginTop: 0 }}>
              {xai.notes.map((n, i) => (
                <li key={i}>{tr(n)}</li>
              ))}
            </ul>
            {xai.xai_consistency.disclaimer && (
              <p className="muted" style={{ fontSize: 12.5 }}>
                {tr(xai.xai_consistency.disclaimer)}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
