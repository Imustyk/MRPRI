import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import { dateLabel, getJson, int, mdl, val, type Tender } from "../api";
import { BandBadge, ErrorNote, PageHead, Skeleton } from "../ui";
import { tr } from "../i18n/backendMap";

/** The four detectors, in run order. Verdicts arrive per record in model_flags. */
const DETECTORS: { key: string; labelKey: string }[] = [
  { key: "statistical_mad_zscore", labelKey: "tenderDetail.det_mad" },
  { key: "isolation_forest", labelKey: "tenderDetail.det_iforest" },
  { key: "local_outlier_factor", labelKey: "tenderDetail.det_lof" },
  { key: "one_class_svm", labelKey: "tenderDetail.det_svm" },
];

export default function TenderDetail() {
  const { t } = useTranslation();
  const { id } = useParams();
  const [tender, setTender] = useState<Tender | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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

  useEffect(load, [id]);

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
    </div>
  );
}
