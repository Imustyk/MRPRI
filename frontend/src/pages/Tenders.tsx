import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getJson, int, mdl, mtenderUrl, num, pctile, type Tender } from "../api";
import { BandBadge, Empty, ErrorNote, PageHead, Skeleton, TableWrap } from "../ui";

const PAGE = 40;

export default function Tenders() {
  const { t } = useTranslation();
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
    const timer = setTimeout(() => setDebouncedQ(q.trim()), 300);
    return () => clearTimeout(timer);
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
      <PageHead
        kicker={t("tenders.kicker")}
        title={t("tenders.title")}
        lede={t("tenders.lede")}
      />

      <div className="toolbar">
        <div className="field grow">
          <label htmlFor="f-q">{t("tenders.f_search")}</label>
          <input
            id="f-q"
            type="search"
            placeholder={t("tenders.f_search_ph")}
            value={q}
            onChange={(e) => {
              reset();
              setQ(e.target.value);
            }}
          />
        </div>
        <div className="field">
          <label htmlFor="f-level">{t("tenders.f_level")}</label>
          <select
            id="f-level"
            value={level}
            onChange={(e) => {
              reset();
              setLevel(e.target.value);
            }}
          >
            <option value="">{t("tenders.f_level_all")}</option>
            <option value="critical">{t("tenders.f_level_critical")}</option>
            <option value="high">{t("tenders.f_level_high")}</option>
            <option value="medium">{t("tenders.f_level_medium")}</option>
            <option value="low">{t("tenders.f_level_low")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-proc">{t("tenders.f_proc")}</label>
          <select
            id="f-proc"
            value={procedure}
            onChange={(e) => {
              reset();
              setProcedure(e.target.value);
            }}
          >
            <option value="">{t("tenders.f_proc_all")}</option>
            <option value="open">{t("tenders.f_proc_open")}</option>
            <option value="restricted">{t("tenders.f_proc_restricted")}</option>
            <option value="negotiated">{t("tenders.f_proc_negotiated")}</option>
            <option value="small_value">{t("tenders.f_proc_small")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-risk">{t("tenders.f_risk", { v: minRisk })}</label>
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
            {t("tenders.clear")}
          </button>
        )}
      </div>

      {err ? <ErrorNote error={err} /> : null}

      {loading ? (
        <Skeleton rows={8} height={34} />
      ) : items.length === 0 ? (
        <Empty
          title={t("tenders.empty")}
          hint={
            filtered ? t("tenders.empty_hint_filtered") : t("tenders.empty_hint")
          }
          action={
            filtered ? (
              <button className="ghost" onClick={clearAll}>
                {t("tenders.clear")}
              </button>
            ) : null
          }
        />
      ) : (
        <TableWrap wide>
          <table>
            <caption className="muted" style={{ captionSide: "top", textAlign: "left", padding: "10px 10px 0" }}>
              {t("tenders.caption", { n: num(total) })}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("tenders.th_priority")}</th>
                <th scope="col">{t("tenders.th_procedure")}</th>
                <th scope="col">{t("tenders.th_buyer")}</th>
                <th scope="col">{t("tenders.th_winner")}</th>
                <th scope="col">{t("tenders.th_award")}</th>
                <th scope="col">{t("tenders.th_bidders")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  key={row.tender_id}
                  className="clickable"
                  // Mouse convenience only. The keyboard and screen-reader path
                  // is the real link on the procedure title below, so this row
                  // is not put in the tab order.
                  onClick={(e) => {
                    if ((e.target as HTMLElement).closest("a, button")) return;
                    nav(`/tenders/${row.tender_id}`);
                  }}
                >
                  <td>
                    <strong className="mono">{pctile(row.risk_score)}</strong>
                    <div>
                      <BandBadge level={row.risk_level} nModels={row.n_models_flagging} />
                    </div>
                  </td>
                  <td>
                    <Link to={`/tenders/${row.tender_id}`}>
                      {row.title ?? t("tenders.untitled")}
                    </Link>
                    {/* External source of record; the row click handler above
                        skips anchors, and stopPropagation keeps it explicit. */}
                    {row.ocid && (
                      <a
                        className="ext-arrow"
                        href={mtenderUrl(row.ocid)}
                        target="_blank"
                        rel="noreferrer noopener"
                        title={t("common.open_mtender")}
                        aria-label={t("common.open_mtender")}
                        onClick={(e) => e.stopPropagation()}
                      >
                        ↗
                      </a>
                    )}
                    <div className="muted mono">{row.tender_id}</div>
                  </td>
                  <td>{row.buyer_name ?? "—"}</td>
                  <td>{row.winner_name ?? "—"}</td>
                  <td className="mono">
                    {row.award_total_mdl === null ? "—" : mdl(row.award_total_mdl)}
                  </td>
                  <td className="mono">{int(row.n_bidders)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      )}

      {/* The table rows themselves are not focusable, so this list gives
          keyboard and screen-reader users the same navigation. */}
      {items.length > 0 && (
        <nav className="muted" aria-label={t("tenders.open_nav")} style={{ marginTop: 10, fontSize: 12 }}>
          {t("tenders.open_directly")}{" "}
          {items.slice(0, 6).map((row) => (
            <span key={row.tender_id}>
              <Link to={`/tenders/${row.tender_id}`} className="mono" style={{ marginRight: 10 }}>
                {row.tender_id}
              </Link>
            </span>
          ))}
        </nav>
      )}

      <div className="pager">
        <button className="ghost" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          {t("tenders.prev")}
        </button>
        <span>
          {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE, total)}`} {t("tenders.of")} {num(total)}
        </span>
        <button className="ghost" disabled={offset + PAGE >= total || loading} onClick={() => setOffset(offset + PAGE)}>
          {t("tenders.next")}
        </button>
      </div>
    </div>
  );
}
