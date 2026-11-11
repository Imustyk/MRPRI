import { safeReturnTo, researchDestination } from "../navigation";
import { Fragment } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { dateLabel, mdl, mtenderUrl } from "../api";
import { tr } from "../i18n/backendMap";
import { BandBadge, ErrorNote, Loading, PageHead, Pill, Skeleton, TableWrap } from "../ui";
import { ProcedureActions } from "../components/ProcedureActions";
import { IndicatorPanel } from "../components/IndicatorPanel";
import { ModelWorkbench, metric } from "../components/ModelExplanationCard";
import { useProcedureData } from "../components/useProcedureData";

const money = (value: number | null) => value === null ? "—" : mdl(value);

export default function TenderDetail() {
  const { t } = useTranslation();
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const returnTo = safeReturnTo(params.get("returnTo"));
  const data = useProcedureData(id);
  const tender = data.tender;
  if (data.loading) return <div><h1>{t("tenderDetail.loading_title")}</h1><Skeleton rows={5} height={40} /></div>;
  if (data.error || !tender) return <div><Link className="back-link" to={returnTo}>← {t("tenderDetail.back")}</Link><h1>{t(data.errorStatus === 404 ? "tenderDetail.not_found_title" : "completion.load_error")}</h1>{data.error && <ErrorNote error={data.error} onRetry={data.retry} />}</div>;
  const facts: [string, string][] = [
    [t("tenderDetail.cf_authority"), tender.buyer_name ?? "—"],
    ["OCID", tender.ocid ?? "—"],
    [t("tenderDetail.cf_cpv"), tender.cpv_code ?? "—"],
    [t("analysis.package_date"), dateLabel(tender.published_at)],
    [t("tenderDetail.cf_deadline"), dateLabel(tender.bid_deadline)],
    [t("tenderDetail.cf_estimate"), money(tender.estimated_value_mdl)],
    [t("tenderDetail.cf_award_total"), money(tender.award_total_mdl)],
    [t("tenderDetail.cf_method"), tender.procedure ?? tender.procurement_method ?? "—"],
    [t("tenderDetail.cf_status"), tender.status ?? "—"],
    [t("tenderDetail.cf_winner"), tender.winner_name ?? "—"],
  ];
  return <div className="tender-analysis">
    <Link className="back-link" to={returnTo}>← {t("tenderDetail.back")}</Link>
    <PageHead kickerPlain kicker={tender.ocid ?? id} title={tender.title ?? t("tenderDetail.untitled")} lede={tender.buyer_name ?? undefined} actions={<>
      {tender.ocid && <a className="action-secondary" href={mtenderUrl(tender.ocid)} target="_blank" rel="noreferrer noopener">{t("common.open_mtender")} ↗</a>}
      <Link className="action-secondary" to={researchDestination("/models", id, returnTo)}>{t("analysis.models_title")} →</Link>
    </>} />
    <section className="surface case-facts" aria-labelledby="review-title">
      <h2 id="review-title">{t("product.review")}</h2>
      <p>{t(tender.risk_score == null || tender.risk_level === "unscored" ? "product.unavailablePriority" : `product.${tender.risk_level}Priority`)}</p>
      <p className="microcopy">{t("analysis.disclaimer")}</p>
    </section>
    <nav className="case-section-nav" aria-label={t("analysis.case_sections")}><a href="#case-facts">{t("analysis.facts")}</a><a href="#case-indicators">{t("product.why")}</a><a href="#case-models">{t("analysis.compare_models")}</a><a href="#case-actions">{t("product.next")}</a></nav>
    <section id="case-facts" className="surface case-facts">
      <div className="section-heading"><h2>{t("analysis.facts")}</h2><BandBadge level={tender.risk_level} nModels={tender.n_models_flagging} /></div>
      <dl className="facts-grid">{facts.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <div className="flags"><Pill tone={tender.has_bid_data ? "info" : "muted"}>{t(tender.has_bid_data ? "analysis.bid_data_available" : "analysis.bid_data_missing")}</Pill><Pill tone={tender.has_award_data ? "info" : "muted"}>{t(tender.has_award_data ? "analysis.award_data_available" : "analysis.award_data_missing")}</Pill></div>
      <details className="research-disclosure"><summary>{t("analysis.additional_facts")}</summary><dl className="kv">
        <dt>{t("tenderDetail.cf_window")}</dt><dd>{metric(tender.bid_window_days)} · {t("analysis.days")}</dd>
        <dt>{t("tenderDetail.comp_bidders")}</dt><dd>{tender.has_bid_data === true ? metric(tender.n_bidders, 0) : t("analysis.unavailable")}</dd>
        <dt>{t("tenderDetail.comp_bid_records")}</dt><dd>{tender.has_bid_data === true ? metric(tender.n_bid_records, 0) : t("analysis.unavailable")}</dd>
        <dt>{t("tenderDetail.comp_lots")}</dt><dd>{metric(tender.n_lots, 0)}</dd>
        <dt>{t("tenderDetail.cf_award_first")}</dt><dd>{money(tender.award_value_mdl)}</dd>
        <dt>{t("tenderDetail.cf_winner_idno")}</dt><dd>{tender.winner_idno ?? "—"}</dd>
      </dl><p className="microcopy">{t("analysis.raw_facts_limit")}</p></details>
    </section>
    <section id="case-indicators"><IndicatorPanel tender={tender} plain /></section>
    <section id="case-models">
      {data.analysisError && <ErrorNote error={data.analysisError} onRetry={data.retryAnalysis} />}
      {!data.analysis && !data.analysisError && <Loading label={t("analysis.loading_models")} />}
      {data.analysis && <ModelWorkbench tender={tender} analysis={data.analysis} showEmpty={false} />}
    </section>
    <ProcedureActions key={id} tender={tender} />
    <details id="case-evidence" className="surface evidence-panel research-disclosure">
      <summary>{t("analysis.evidence")}</summary>
      <p className="microcopy break-anywhere">{t("analysis.source")}: {data.analysis?.source ?? t("analysis.unavailable")} · {t("analysis.run")}: <code>{data.analysis?.run_id ?? "—"}</code></p>
      <p className="microcopy">{t("analysis.run_date")}: {dateLabel(data.analysis?.generated_at)} · {t("analysis.reference_size")}: {metric(data.analysis?.n_reference, 0)}</p>
      {data.explanationError && <ErrorNote error={data.explanationError} onRetry={data.retryExplanation} />}
      {data.explanationLoading && <Loading />}
      {data.explanation ? data.explanation.layers.map((layer) => <details className="research-disclosure" key={layer.id}><summary>{t(`tenderDetail.${({ facts: "explainLayerFacts", indicators: "explainLayerIndicators", detectors: "explainLayerDetectors", references: "explainLayerReferences", limitations: "explainLayerLimitations" })[layer.id]}`)}</summary>
        {layer.id === "facts" ? <dl className="kv">{layer.items.map((item) => <Fragment key={item.field}><dt>{tr(item.label)}</dt><dd>{item.value === null ? "—" : String(item.value)}{item.percentile != null && tender.score_provenance?.run_id && tender.score_provenance.run_id === data.explanation?.scoring_run_id && <span className="microcopy" title={t("tenderDetail.explain_pct_hint")}> · {t("tenderDetail.explain_pct", { v: metric(item.percentile, 1) })}</span>}</dd></Fragment>)}</dl>
        : layer.id === "references" ? <ul className="evidence-list">{layer.items.map((item) => <li key={item.path}><strong>{tr(item.label)}</strong><code>{item.path}</code><Pill tone={item.available ? "info" : "muted"}>{t(item.available ? "analysis.reference_present" : "analysis.unavailable")}</Pill></li>)}</ul>
        : layer.id === "limitations" ? <ul>{layer.items.map((item, i) => <li key={i}>{tr(item.text)}</li>)}</ul>
        : layer.id === "detectors" ? <TableWrap><table><thead><tr><th scope="col">{t("analysis.model")}</th><th scope="col">{t("analysis.raw_score")}</th><th scope="col">{t("analysis.verdict")}</th></tr></thead><tbody>{layer.items.map((item) => <tr key={item.key}><th scope="row">{item.label}</th><td>{metric(item.score, 6)}</td><td>{t(item.verdict === "unscored" ? "analysis.unavailable" : `analysis.${item.verdict}`)}</td></tr>)}</tbody></table></TableWrap>
        : <ul>{layer.items.map((item) => <li key={item.key}>{tr(item.label)}: {t(item.triggered ? "analysis.recorded_signal" : "analysis.not_recorded")} · {t("analysis.corpus_frequency")}: {item.corpus_rate === null ? "—" : `${metric(item.corpus_rate * 100, 2)}%`} (n = {metric(item.corpus_n, 0)})</li>)}</ul>}
      </details>) : !data.explanationLoading && !data.explanationError ? <p className="muted">{t("analysis.explanation_unavailable")}</p> : null}
      <p className="microcopy">{t("analysis.peer_limit")}</p>
    </details>
  </div>;
}
