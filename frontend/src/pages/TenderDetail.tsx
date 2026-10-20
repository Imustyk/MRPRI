import { Fragment, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import {
  dateLabel,
  getJson,
  getTenderExplanation,
  int,
  mdl,
  mtenderUrl,
  pct,
  pctile,
  val,
  type ExplanationDetectorItem,
  type ExplanationFactItem,
  type ExplanationIndicatorItem,
  type ExplanationLayer,
  type ExplanationLimitationItem,
  type ExplanationReferenceItem,
  type Tender,
  type TenderExplanation,
} from "../api";
import { BandBadge, ErrorNote, PageHead, Pill, Skeleton, TableWrap } from "../ui";
import { tr } from "../i18n/backendMap";

/** The four detectors, in run order. Verdicts arrive per record in model_flags. */
const DETECTORS: { key: string; labelKey: string }[] = [
  { key: "statistical_mad_zscore", labelKey: "tenderDetail.det_mad" },
  { key: "isolation_forest", labelKey: "tenderDetail.det_iforest" },
  { key: "local_outlier_factor", labelKey: "tenderDetail.det_lof" },
  { key: "one_class_svm", labelKey: "tenderDetail.det_svm" },
];

const DETECTOR_LABEL_KEY: Record<string, string> = Object.fromEntries(
  DETECTORS.map((d) => [d.key, d.labelKey]),
);

/**
 * Observed-fact fields whose generic server label has no catalog entry of its
 * own; every other label localises through the backend map ("CPV code",
 * "Published", "Distinct bidders", …).
 */
const FACT_LABEL_KEY: Record<string, string> = {
  title: "tenderDetail.cf_title",
  bid_deadline: "tenderDetail.cf_deadline",
  award_date: "tenderDetail.cf_award_decision",
  award_value_mdl: "tenderDetail.cf_award_first",
  award_total_mdl: "tenderDetail.cf_award_total",
  buyer_name: "tenderDetail.cf_authority",
  buyer_locality: "tenderDetail.cf_locality",
  winner_idno: "tenderDetail.cf_winner_idno",
  tender_id: "tenderDetail.cf_tender_id",
};

/** ISO date fields rendered as localised dates rather than raw strings. */
const DATE_FIELDS = new Set(["published_at", "tender_start", "bid_deadline", "award_date"]);

/** Money in MDL, counts as integers, dates localised; null never fakes a 0. */
function factValue(f: ExplanationFactItem): string {
  if (f.value === null || f.value === "") return "\u2014";
  if (typeof f.value === "string") {
    return DATE_FIELDS.has(f.field) ? dateLabel(f.value) : f.value;
  }
  if (f.field.endsWith("_mdl")) return mdl(f.value);
  return int(f.value);
}

/** Narrowed items of one layer; an id the server omitted renders as empty. */
function itemsOf(expl: TenderExplanation, id: "facts"): ExplanationFactItem[];
function itemsOf(expl: TenderExplanation, id: "indicators"): ExplanationIndicatorItem[];
function itemsOf(expl: TenderExplanation, id: "detectors"): ExplanationDetectorItem[];
function itemsOf(expl: TenderExplanation, id: "references"): ExplanationReferenceItem[];
function itemsOf(expl: TenderExplanation, id: "limitations"): ExplanationLimitationItem[];
function itemsOf(
  expl: TenderExplanation,
  id: ExplanationLayer["id"],
): ExplanationLayer["items"][number][] {
  const hit = expl.layers.find((l) => l.id === id);
  return hit ? hit.items : [];
}

export default function TenderDetail() {
  const { t } = useTranslation();
  const { id } = useParams();
  const [tender, setTender] = useState<Tender | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [expl, setExpl] = useState<TenderExplanation | null>(null);
  const [explErr, setExplErr] = useState<string | null>(null);
  const [explLoading, setExplLoading] = useState(false);

  const load = () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    getJson<Tender>(`/api/tenders/${id}`)
      .then((d) => {
        setTender(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  };

  // Loaded separately and lazily with the page: the explanation is a heavier
  // aggregate, and a failure here must never take the record view down.
  const loadExplain = () => {
    if (!id) return;
    setExplLoading(true);
    setExplErr(null);
    getTenderExplanation(id)
      .then((d) => {
        setExpl(d);
        setExplLoading(false);
      })
      .catch((e: Error) => {
        setExplErr(e.message);
        setExplLoading(false);
      });
  };

  useEffect(load, [id]);
  useEffect(() => {
    loadExplain();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (loading) {
    return (
      <div>
        <Link to="/tenders" className="back-link">
          {t("tenderDetail.back")}
        </Link>
        <h1 style={{ marginTop: 10 }}>{t("tenderDetail.loading_title")}</h1>
        <Skeleton rows={3} height={40} />
        <Skeleton rows={6} />
      </div>
    );
  }

  if (error || !tender) {
    return (
      <div>
        <Link to="/tenders" className="back-link">
          {t("tenderDetail.back")}
        </Link>
        <h1 style={{ marginTop: 10 }}>{t("tenderDetail.not_found_title")}</h1>
        <p className="lede">
          <Trans i18nKey="tenderDetail.not_found_lede" values={{ id }} components={{ code: <code /> }} />
        </p>
        <ErrorNote error={error ?? t("tenderDetail.no_record")} onRetry={load} />
        <div style={{ marginTop: 16 }}>
          <Link to="/tenders" className="back-link">
            {t("tenderDetail.back_to_all")}
          </Link>
        </div>
      </div>
    );
  }

  const flags = Array.isArray(tender.flags) ? tender.flags : [];
  const hasBids = (tender.n_bidders ?? 0) > 0;
  const multiLot = (tender.n_lots ?? 0) > 1;

  return (
    <div>
      <Link to="/tenders" className="back-link">
        {t("tenderDetail.back")}
      </Link>
      <PageHead
        kickerPlain
        kicker={tender.tender_id ?? tender.ocid ?? "—"}
        title={tender.title ?? t("tenderDetail.untitled")}
        lede={
          [tender.buyer_name, tender.buyer_locality, tender.procedure, tender.status]
            .filter(Boolean)
            .join(" · ") || t("tenderDetail.no_meta")
        }
      />

      {/* The source of record, when the OCDS identifier is known. */}
      {tender.ocid && (
        <p className="ext-link-row">
          <a
            className="ext-link"
            href={mtenderUrl(tender.ocid)}
            target="_blank"
            rel="noreferrer noopener"
          >
            {t("common.open_mtender")} <span aria-hidden="true">↗</span>
          </a>
        </p>
      )}

      <div className="detail-grid">
        <div className="card">
          <h2>
            {t("tenderDetail.band_h")}{" "}
            <BandBadge level={tender.risk_level} nModels={tender.n_models_flagging} />
          </h2>
          <p className="muted">
            {t("tenderDetail.band_note", { n: tender.n_models_flagging ?? 0 })}
          </p>
          <p>
            {t("tenderDetail.percentile")}{" "}
            <strong className="mono">{val(tender.risk_score, 1)}</strong> / 100
          </p>
          <p className="muted">
            {t("tenderDetail.scores", {
              mad: val(tender.rule_score, 2),
              iso: val(tender.iso_score, 3),
              lof: val(tender.lof_score, 1),
              svm: val(tender.svm_score, 3),
            })}
          </p>
          {tender.model_flags && (
            <div className="flags" style={{ marginTop: 10 }}>
              {DETECTORS.map(({ key, labelKey }) => {
                const verdict = tender.model_flags[key];
                const text =
                  verdict === true
                    ? t("tenderDetail.verdict_flagged")
                    : verdict === false
                      ? t("tenderDetail.verdict_cleared")
                      : t("tenderDetail.verdict_unscored");
                const cls =
                  verdict === true
                    ? "flag"
                    : verdict === false
                      ? "flag clear"
                      : "flag unscored";
                return (
                  <span key={key} className={cls}>
                    {t(labelKey)}: {text}
                  </span>
                );
              })}
            </div>
          )}

          <h2 style={{ marginTop: 20 }}>{t("tenderDetail.flags_h")}</h2>
          <div className="flags">
            {flags.length ? (
              flags.map((f) => (
                <span key={f} className="flag">
                  {tr(f)}
                </span>
              ))
            ) : (
              <span className="muted">{t("tenderDetail.flags_none")}</span>
            )}
          </div>

          <h2 style={{ marginTop: 20 }}>{t("tenderDetail.comp_h")}</h2>
          <dl className="kv">
            <dt>{t("tenderDetail.comp_bidders")}</dt>
            <dd className="mono">{int(tender.n_bidders)}</dd>
            <dt>{t("tenderDetail.comp_bid_records")}</dt>
            <dd className="mono">{int(tender.n_bid_records)}</dd>
            <dt>{t("tenderDetail.comp_lots")}</dt>
            <dd className="mono">{int(tender.n_lots)}</dd>
          </dl>
          <p className="muted" style={{ marginTop: 12 }}>
            {hasBids ? (
              <Trans
                i18nKey="tenderDetail.bids_note"
                count={tender.n_lots ?? 0}
                values={{
                  records: int(tender.n_bid_records),
                  lots: int(tender.n_lots),
                  bidders: int(tender.n_bidders),
                }}
                components={{ code: <code /> }}
              />
            ) : (
              <Trans i18nKey="tenderDetail.no_bids_note" />
            )}
          </p>
        </div>

        <div className="card">
          <h2>{t("tenderDetail.case_h")}</h2>
          <dl className="kv">
            <dt>{t("tenderDetail.cf_cpv")}</dt>
            <dd className="mono">{tender.cpv_code ?? "—"}</dd>
            <dt>{t("tenderDetail.cf_published")}</dt>
            <dd>{dateLabel(tender.published_at)}</dd>
            <dt>{t("tenderDetail.cf_deadline")}</dt>
            <dd>{dateLabel(tender.bid_deadline)}</dd>
            <dt>{t("tenderDetail.cf_window")}</dt>
            <dd className="mono">
              {tender.bid_window_days === null || tender.bid_window_days === undefined
                ? "—"
                : t("tenderDetail.cf_days", { count: tender.bid_window_days })}
            </dd>
            <dt>{t("tenderDetail.cf_status")}</dt>
            <dd>{tender.status ?? "—"}</dd>
            <dt>{t("tenderDetail.cf_method")}</dt>
            <dd>{tender.procurement_method ?? "—"}</dd>
            <dt>{t("tenderDetail.cf_estimate")}</dt>
            <dd className="mono">
              {tender.estimated_value_mdl === null ? "—" : mdl(tender.estimated_value_mdl)}
            </dd>
            <dt>{t("tenderDetail.cf_award_first")}</dt>
            <dd className="mono">
              {tender.award_value_mdl === null ? "—" : mdl(tender.award_value_mdl)}
            </dd>
            <dt>{t("tenderDetail.cf_award_total")}</dt>
            <dd className="mono">
              {tender.award_total_mdl === null ? "—" : mdl(tender.award_total_mdl)}
            </dd>
            <dt>{t("tenderDetail.cf_winner")}</dt>
            <dd>{tender.winner_name ?? "—"}</dd>
            <dt>{t("tenderDetail.cf_winner_idno")}</dt>
            <dd className="mono">{tender.winner_idno ?? "—"}</dd>
          </dl>
          {multiLot && (
            <p className="muted" style={{ marginTop: 12 }}>
              {t("tenderDetail.multilot_note", { count: tender.n_lots ?? 0 })}
            </p>
          )}
          <p className="muted" style={{ marginTop: 16 }}>
            <Trans i18nKey="tenderDetail.legal_note" />
          </p>
        </div>
      </div>

      {/* Layered explanation: facts, indicators, detector verdicts, sources,
          limitations — kept apart so no layer can read as another. */}
      <div className="card" style={{ marginTop: 16 }}>
        <h2>{t("tenderDetail.explain_h")}</h2>
        <p className="muted">{t("tenderDetail.explain_p")}</p>

        {explLoading ? (
          <Skeleton rows={5} />
        ) : explErr ? (
          <ErrorNote error={explErr} onRetry={loadExplain} />
        ) : !expl ? (
          <p className="muted">{t("tenderDetail.explain_na")}</p>
        ) : (
          <>
            <p className="muted mono" style={{ fontSize: 12 }}>
              {t("tenderDetail.explain_meta", {
                version: expl.model_version,
                run: expl.scoring_run_id ?? "\u2014",
                date: expl.scoring_generated_at ?? "\u2014",
              })}
            </p>

            <h3 style={{ marginTop: 14 }}>{t("tenderDetail.explainLayerFacts")}</h3>
            <dl className="kv">
              {itemsOf(expl, "facts").map((f) => (
                <Fragment key={f.field}>
                  <dt>{FACT_LABEL_KEY[f.field] ? t(FACT_LABEL_KEY[f.field]) : tr(f.label)}</dt>
                  <dd className="mono">
                    {factValue(f)}
                    {f.percentile !== null && f.percentile !== undefined && (
                      <span
                        className="muted"
                        style={{ marginLeft: 8, fontSize: 12 }}
                        title={t("tenderDetail.explain_pct_hint")}
                      >
                        {t("tenderDetail.explain_pct", { v: pctile(f.percentile) })}
                      </span>
                    )}
                  </dd>
                </Fragment>
              ))}
            </dl>

            <h3 style={{ marginTop: 16 }}>{t("tenderDetail.explainLayerIndicators")}</h3>
            <div className="flags">
              {itemsOf(expl, "indicators").map((i) => (
                <span key={i.key} className={i.triggered ? "flag" : "flag clear"}>
                  <strong>{tr(i.label)}</strong>:{" "}
                  {i.triggered
                    ? t("tenderDetail.explain_triggered")
                    : t("tenderDetail.explain_not_triggered")}
                  {i.corpus_rate !== null && i.corpus_rate !== undefined && (
                    <>
                      {" · "}
                      {t("tenderDetail.explain_rate", {
                        rate: pct(i.corpus_rate),
                        n: int(i.corpus_n),
                      })}
                    </>
                  )}
                </span>
              ))}
            </div>

            <h3 style={{ marginTop: 16 }}>{t("tenderDetail.explainLayerDetectors")}</h3>
            <TableWrap>
              <table>
                <thead>
                  <tr>
                    <th scope="col">{t("kpis.cat_th_detector")}</th>
                    <th scope="col">{t("tenderDetail.explain_th_verdict")}</th>
                    <th scope="col">{t("tenderDetail.explain_th_score")}</th>
                    <th scope="col">{t("tenderDetail.explain_th_pct")}</th>
                  </tr>
                </thead>
                <tbody>
                  {itemsOf(expl, "detectors").map((d) => (
                    <tr key={d.key}>
                      <td>{DETECTOR_LABEL_KEY[d.key] ? t(DETECTOR_LABEL_KEY[d.key]) : tr(d.label)}</td>
                      <td>
                        <Pill
                          tone={
                            d.verdict === "flagged"
                              ? "risk"
                              : d.verdict === "not_flagged"
                                ? "ok"
                                : "muted"
                          }
                        >
                          {d.verdict === "flagged"
                            ? t("tenderDetail.verdict_flagged")
                            : d.verdict === "not_flagged"
                              ? t("tenderDetail.verdict_cleared")
                              : t("tenderDetail.verdict_unscored")}
                        </Pill>
                      </td>
                      <td className="mono">{val(d.score, 3)}</td>
                      <td className="mono">
                        {t("tenderDetail.explain_pct", { v: pctile(d.score_percentile) })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>

            <h3 style={{ marginTop: 16 }}>{t("tenderDetail.explainLayerReferences")}</h3>
            <ul className="muted" style={{ paddingLeft: 18, marginTop: 0 }}>
              {itemsOf(expl, "references").map((r) => (
                <li key={r.path} style={r.available ? undefined : { opacity: 0.65 }}>
                  {tr(r.label)}{" "}
                  <span className="mono" style={{ fontSize: 12 }}>
                    {r.path}
                  </span>
                  {!r.available && (
                    <>
                      {" — "}
                      <em>{t("tenderDetail.explain_source_na")}</em>
                    </>
                  )}
                </li>
              ))}
            </ul>

            <h3 style={{ marginTop: 16 }}>{t("tenderDetail.explainLayerLimitations")}</h3>
            <ul style={{ paddingLeft: 18, marginTop: 0 }}>
              {itemsOf(expl, "limitations").map((l, idx) => (
                <li key={idx} className="muted">
                  {tr(l.text)}
                </li>
              ))}
            </ul>
            <p className="muted" style={{ marginTop: 12, fontSize: 12.5 }}>
              {t("tenderDetail.explain_disclaimer")}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
