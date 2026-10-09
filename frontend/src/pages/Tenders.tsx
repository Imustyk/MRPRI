import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getJson, int, mdl, num, pctile, type Tender } from "../api";
import { BandBadge, Empty, ErrorNote, Skeleton, TableWrap } from "../ui";

const PAGE = 40;

export default function Tenders() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  // Debounced so a request is not fired per keystroke; the upstream API is
  // fragile and also rate-limited.
  const [debouncedQ, setDebouncedQ] = useState("");
  const [level, setLevel] = useState("");
  const [procedure, setProcedure] = useState("");
  const [minRisk, setMinRisk] = useState(0);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<Tender[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({
      limit: String(PAGE),
      offset: String(offset),
      min_risk: String(minRisk),
    });
    if (debouncedQ) params.set("q", debouncedQ);
    if (level) params.set("level", level);
    if (procedure) params.set("procedure", procedure);

    // A cancelled request must not overwrite the results of a newer one.
    let live = true;
    getJson<{ total: number; items: Tender[] }>(`/api/tenders?${params}`)
      .then((d) => {
        if (!live) return;
        setErr(null);
        setTotal(d.total);
        setItems(d.items);
        setLoading(false);
      })
      .catch((e: Error) => {
        if (!live) return;
        setErr(e.message);
        setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [debouncedQ, level, procedure, minRisk, offset]);

  const reset = () => setOffset(0);
  const filtered = Boolean(q || level || procedure || minRisk > 0);
  const clearAll = () => {
    setQ("");
    setLevel("");
    setProcedure("");
    setMinRisk(0);
    reset();
  };

  return (
    <div>
      <div className="kicker">Ranked procedures</div>
      <h1>Scored tenders</h1>
      <p className="lede">
        Procedures from the real MTender feed, sorted by anomaly percentile. The band shows how many
        of the four detectors agreed; the number is a rank within this dataset, not a probability.
        Open a row for the full breakdown.
      </p>

      <div className="toolbar">
        <div className="field grow">
          <label htmlFor="f-q">Search</label>
          <input
            id="f-q"
            type="search"
            placeholder="Buyer, winner, title or OCID"
            value={q}
            onChange={(e) => {
              reset();
              setQ(e.target.value);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="f-level">Priority band</label>
          <select
            id="f-level"
            value={level}
            onChange={(e) => {
              reset();
              setLevel(e.target.value);
            }}
          >
            <option value="">All bands</option>
            <option value="critical">Critical (3+ detectors)</option>
            <option value="high">High (2 detectors)</option>
            <option value="medium">Medium (1 detector)</option>
            <option value="low">Low (0 detectors)</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-proc">Procedure</label>
          <select
            id="f-proc"
            value={procedure}
            onChange={(e) => {
              reset();
              setProcedure(e.target.value);
            }}
          >
            <option value="">All procedures</option>
            <option value="open">Open</option>
            <option value="restricted">Restricted</option>
            <option value="negotiated">Negotiated</option>
            <option value="small_value">Small value</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-risk">Min anomaly percentile: {minRisk}</label>
          <input
            id="f-risk"
            type="range"
            min={0}
            max={95}
            step={5}
            value={minRisk}
            onChange={(e) => {
              reset();
              setMinRisk(Number(e.target.value));
            }}
          />
        </div>
        {filtered && (
          <button className="ghost" onClick={clearAll}>
            Clear filters
          </button>
        )}
      </div>

      {err ? <ErrorNote error={err} /> : null}

      {loading ? (
        <Skeleton rows={8} height={34} />
      ) : items.length === 0 ? (
        <Empty
          title="No procedure matches these filters"
          hint={
            filtered
              ? "Widen the percentile range or clear the search text."
              : "The export contains no procedures."
          }
          action={
            filtered ? (
              <button className="ghost" onClick={clearAll}>
                Clear filters
              </button>
            ) : null
          }
        />
      ) : (
        <TableWrap wide>
          <table>
            <caption className="muted" style={{ captionSide: "top", textAlign: "left", padding: "10px 10px 0" }}>
              Sorted by anomaly percentile, descending. {num(total)} matching procedures.
            </caption>
            <thead>
              <tr>
                <th scope="col">Priority</th>
                <th scope="col">Procedure</th>
                <th scope="col">Buyer</th>
                <th scope="col">Winner</th>
                <th scope="col">Award (all lots)</th>
                <th scope="col">Bidders</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr
                  key={t.tender_id}
                  className="clickable"
                  // Mouse convenience only. The keyboard and screen-reader path
                  // is the real link on the procedure title below, so this row
                  // is not put in the tab order.
                  onClick={(e) => {
                    if ((e.target as HTMLElement).closest("a, button")) return;
                    nav(`/tenders/${t.tender_id}`);
                  }}
                >
                  <td>
                    <strong className="mono">{pctile(t.risk_score)}</strong>
                    <div>
                      <BandBadge level={t.risk_level} nModels={t.n_models_flagging} />
                    </div>
                  </td>
                  <td>
                    <Link to={`/tenders/${t.tender_id}`}>
                      {t.title ?? "Untitled procedure"}
                    </Link>
                    <div className="muted mono">{t.tender_id}</div>
                  </td>
                  <td>{t.buyer_name ?? "—"}</td>
                  <td>{t.winner_name ?? "—"}</td>
                  <td className="mono">
                    {t.award_total_mdl === null ? "—" : mdl(t.award_total_mdl)}
                  </td>
                  <td className="mono">{int(t.n_bidders)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}

      {/* The table rows themselves are not focusable, so this list gives
          keyboard and screen-reader users the same navigation. */}
      {items.length > 0 && (
        <nav className="muted" aria-label="Open a procedure" style={{ marginTop: 10, fontSize: 12 }}>
          Open directly:{" "}
          {items.slice(0, 6).map((t) => (
            <span key={t.tender_id}>
              <Link to={`/tenders/${t.tender_id}`} className="mono" style={{ marginRight: 10 }}>
                {t.tender_id}
              </Link>
            </span>
          ))}
        </nav>
      )}

      <div className="pager">
        <button className="ghost" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          Previous
        </button>
        <span>
          {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE, total)}`} of {num(total)}
        </span>
        <button className="ghost" disabled={offset + PAGE >= total || loading} onClick={() => setOffset(offset + PAGE)}>
          Next
        </button>
      </div>
    </div>
  );
}
