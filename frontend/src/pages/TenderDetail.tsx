import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { dateLabel, getJson, int, mdl, val, type Tender } from "../api";
import { BandBadge, ErrorNote, Skeleton } from "../ui";

export default function TenderDetail() {
  const { id } = useParams();
  const [t, setT] = useState<Tender | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    getJson<Tender>(`/api/tenders/${id}`)
      .then((d) => {
        setT(d);
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
        <Link to="/tenders" className="muted">
          ← All procedures
        </Link>
        <h1 style={{ marginTop: 10 }}>Loading procedure…</h1>
        <Skeleton rows={3} height={40} />
        <Skeleton rows={6} />
      </div>
    );
  }

  if (error || !t) {
    return (
      <div>
        <Link to="/tenders" className="muted">
          ← All procedures
        </Link>
        <h1 style={{ marginTop: 10 }}>Procedure not found</h1>
        <p className="lede">
          Nothing is stored for <code>{id}</code>. It may belong to a pipeline run that has since
          been replaced, or the identifier may be mistyped.
        </p>
        <ErrorNote error={error ?? "No record returned."} onRetry={load} />
        <div style={{ marginTop: 16 }}>
          <Link to="/tenders" className="muted">
            Back to all procedures →
          </Link>
        </div>
      </div>
    );
  }

  const flags = Array.isArray(t.flags) ? t.flags : [];
  const hasBids = (t.n_bidders ?? 0) > 0;
  const multiLot = (t.n_lots ?? 0) > 1;

  return (
    <div>
      <Link to="/tenders" className="muted">
        ← All procedures
      </Link>
      <div className="kicker mono">{t.tender_id ?? t.ocid ?? "—"}</div>
      <h1>{t.title ?? "Untitled procedure"}</h1>
      <p className="lede">
        {[t.buyer_name, t.buyer_locality, t.procedure, t.status].filter(Boolean).join(" · ") ||
          "No buyer, locality, procedure type or status was published for this record."}
      </p>

      <div className="detail-grid">
        <div className="card">
          <h2>
            Priority band{" "}
            <BandBadge level={t.risk_level} nModels={t.n_models_flagging} />
          </h2>
          <p className="muted">
            {t.n_models_flagging ?? 0} of 4 detectors flagged this procedure. The band is model
            agreement, not a probability.
          </p>
          <p>
            Anomaly percentile{" "}
            <strong className="mono">{val(t.risk_score, 1)}</strong> / 100
          </p>
          <p className="muted">
            MAD z {val(t.rule_score, 2)} · Isolation Forest {val(t.iso_score, 3)} · LOF{" "}
            {val(t.lof_score, 1)} · One-Class SVM {val(t.svm_score, 3)}
          </p>

          <h2 style={{ marginTop: 20 }}>Red flags</h2>
          <div className="flags">
            {flags.length ? (
              flags.map((f) => (
                <span key={f} className="flag">
                  {f}
                </span>
              ))
            ) : (
              <span className="muted">No rule-based flags were raised.</span>
            )}
          </div>

          <h2 style={{ marginTop: 20 }}>Competition</h2>
          <dl className="kv">
            <dt>Distinct bidders</dt>
            <dd className="mono">{int(t.n_bidders)}</dd>
            <dt>Bid records (per lot)</dt>
            <dd className="mono">{int(t.n_bid_records)}</dd>
            <dt>Lots</dt>
            <dd className="mono">{int(t.n_lots)}</dd>
          </dl>
          <p className="muted" style={{ marginTop: 12 }}>
            {hasBids ? (
              <>
                <code>bids.details</code> holds one entry per lot rather than per bidder, so{" "}
                {int(t.n_bid_records)} records across {int(t.n_lots)} lot
                {t.n_lots === 1 ? "" : "s"} represent {int(t.n_bidders)} distinct tenderers. Only the
                last figure measures competition.
              </>
            ) : (
              <>
                MTender published no participant list for this procedure, so competition cannot be
                assessed. This is missing data, not a finding of zero bidders.
              </>
            )}
          </p>
        </div>

        <div className="card">
          <h2>Case file</h2>
          <dl className="kv">
            <dt>CPV</dt>
            <dd className="mono">{t.cpv_code ?? "—"}</dd>
            <dt>Published</dt>
            <dd>{dateLabel(t.published_at)}</dd>
            <dt>Bid deadline</dt>
            <dd>{dateLabel(t.bid_deadline)}</dd>
            <dt>Window</dt>
            <dd className="mono">{t.bid_window_days ?? "—"} days</dd>
            <dt>Status</dt>
            <dd>{t.status ?? "—"}</dd>
            <dt>Method</dt>
            <dd>{t.procurement_method ?? "—"}</dd>
            <dt>Estimate</dt>
            <dd className="mono">
              {t.estimated_value_mdl === null ? "—" : mdl(t.estimated_value_mdl)}
            </dd>
            <dt>Award (first)</dt>
            <dd className="mono">
              {t.award_value_mdl === null ? "—" : mdl(t.award_value_mdl)}
            </dd>
            <dt>Award total (all lots)</dt>
            <dd className="mono">
              {t.award_total_mdl === null ? "—" : mdl(t.award_total_mdl)}
            </dd>
            <dt>Winner</dt>
            <dd>{t.winner_name ?? "—"}</dd>
            <dt>Winner IDNO</dt>
            <dd className="mono">{t.winner_idno ?? "—"}</dd>
          </dl>
          {multiLot && (
            <p className="muted" style={{ marginTop: 12 }}>
              This procedure was awarded across {int(t.n_lots)} lots. Only the all-lot total is
              comparable with the estimate.
            </p>
          )}
          <p className="muted" style={{ marginTop: 16 }}>
            A high band prioritizes manual review. It does not prove corruption, collusion, or a
            legal violation. MTender publishes no court-confirmed labels, so the detector cannot be
            scored for precision or recall on this source.
          </p>
        </div>
      </div>
    </div>
  );
}
