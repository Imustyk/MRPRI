import { tenderDestination } from "../navigation";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getJson, dateLabel, mdl, num, type Stats, type Tender } from "../api";
import { useRequest } from "../hooks";
import { BandBadge, PageHead, RequestPanel, ErrorNote, Skeleton, TableWrap } from "../ui";

const PAGE = 40;
const ADVANCED_FILTERS = ["date_from", "date_to", "min_value", "max_value", "cpv"] as const;
const EXTRA_FILTERS = [...ADVANCED_FILTERS, "scored", "buyer"] as const;
const LEVELS = new Set(["critical", "high", "medium", "low", "unscored"]);

/**
 * The URL is the state of this page: every filter, the search text and the page
 * offset are read from (and written back to) the query string, so reload, a
 * shared link, Back/Forward and "return from a tender card" all restore the same
 * view. Values that are not sane are coerced to their defaults instead of
 * reaching the API.
 */
export function readTenderFilters(params: URLSearchParams) {
  const q = params.get("q") ?? "";
  const rawLevel = params.get("level") ?? "";
  const level = LEVELS.has(rawLevel) ? rawLevel : "";
  const procedure = params.get("procedure") ?? "";
  const rawMin = params.get("min");
  const parsedMin = rawMin === null ? 0 : Number(rawMin);
  const minRisk =
    rawMin === null || !Number.isFinite(parsedMin)
      ? 0
      : Math.min(95, Math.max(0, Math.round(parsedMin / 5) * 5));
  const rawOffset = params.get("offset");
  const parsedOffset = rawOffset === null ? 0 : Number(rawOffset);
  const offset =
    rawOffset === null || !Number.isSafeInteger(parsedOffset) || parsedOffset <= 0
      ? 0
      : Math.floor(parsedOffset / PAGE) * PAGE;
  const extra = Object.fromEntries(EXTRA_FILTERS.flatMap(key => {
    const value = params.get(key);
    return value ? [[key, value]] : [];
  }));
  return { q, level, procedure, minRisk, offset, extra };
}

type TenderFilters = ReturnType<typeof readTenderFilters>;

export default function Tenders() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = readTenderFilters(searchParams);

  // Debounced so a request is not fired per keystroke; the upstream API is
  // fragile and also rate-limited. The input keeps local text, the URL stays
  // authoritative — the request below only ever reads URL state.
  const [q, setQ] = useState(filters.q);
  const [procedureOptions, setProcedureOptions] = useState<string[]>([]);
  const filtered = Boolean(filters.q || filters.level || filters.procedure || filters.minRisk > 0 || Object.keys(filters.extra).length);

  const options = useRequest("procedure-options", signal => getJson<Stats>("/api/stats", signal));
  const location = useLocation();
  const destination = (id: string) => tenderDestination(id, location.pathname + location.search);
  useEffect(() => { if (options.data && !options.error) setProcedureOptions(Object.keys(options.data.procedure_counts).sort()); }, [options.data, options.error]);

  /** Filter edits replace the current entry (no history spam per keystroke);
   *  paging pushes, so Back steps through pages exactly as visited. */
  const update = useCallback(
    (patch: Record<string, string | number | null>, push: boolean) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [name, value] of Object.entries(patch)) {
            if (value === null || value === "") next.delete(name);
            else next.set(name, String(value));
          }
          return next;
        },
        { replace: !push },
      );
    },
    [setSearchParams],
  );

  // Normalise foreign/invalid parameters once, so the address bar and the
  // request always agree (e.g. ?level=xyz&offset=123 → defaults, via replace so
  // a broken link does not become a history stop).
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    let changed = false;
    const put = (name: string, value: string | null) => {
      if (value === null) {
        if (next.has(name)) {
          next.delete(name);
          changed = true;
        }
      } else if (next.get(name) !== value) {
        next.set(name, value);
        changed = true;
      }
    };
    put("level", filters.level || null);
    put("procedure", filters.procedure || null);
    put("min", filters.minRisk > 0 ? String(filters.minRisk) : null);
    put("offset", filters.offset > 0 ? String(filters.offset) : null);
    if (changed) setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, filters.level, filters.procedure, filters.minRisk, filters.offset]);

  // Keep the input in step with external URL changes (Back/Forward, a new global
  // search) but never overwrite text the user is still typing.
  useEffect(() => {
    if (filters.q !== q.trim()) setQ(filters.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.q]);

  useEffect(() => {
    const trimmed = q.trim();
    if (trimmed === filters.q) return;
    // Debounced write into the URL; the request follows automatically.
    const timer = setTimeout(() => update({ q: trimmed || null, offset: null }, false), 300);
    return () => clearTimeout(timer);
  }, [q, filters.q, update]);

  const requestKey = JSON.stringify(filters);
  const req = useRequest<{ total: number; items: Tender[] }>(requestKey, (signal) => {
    const params = new URLSearchParams({
      sort: "risk",
      limit: String(PAGE),
      offset: String(filters.offset),
      min_risk: String(filters.minRisk),
      ...filters.extra,
    });
    if (filters.q) params.set("q", filters.q);
    if (filters.level) params.set("level", filters.level);
    if (filters.procedure) params.set("procedure", filters.procedure);
    return getJson<{ total: number; items: Tender[] }>(`/api/tenders?${params}`, signal);
  });

  const describe = (raw: string) => {
    let parsed: TenderFilters = filters;
    try {
      parsed = JSON.parse(raw) as TenderFilters;
    } catch {
      /* a hand-written key falls back to the current filters */
    }
    const parts: string[] = [];
    if (parsed.q) parts.push(`“${parsed.q}”`);
    if (parsed.level) parts.push(t(`risk.${parsed.level}`));
    if (parsed.procedure) parts.push(parsed.procedure.replaceAll("_", " "));
    for (const [key, value] of Object.entries(parsed.extra ?? {})) {
      parts.push(key === "scored" ? t(value === "true" ? "product.scored" : "risk.unscored") : value);
    }
    if (parsed.minRisk > 0) parts.push(String(parsed.minRisk));
    return t("tenders.params_desc", {
      page: parsed.offset / PAGE + 1,
      filters: parts.join(" · ") || t("common.all"),
    });
  };

  const data = req.data;
  const total = data?.total ?? 0;
  const setFilter = (patch: Record<string, string | number | null>) =>
    update({ ...patch, offset: null }, false);
  const setPage = (offset: number) => update({ offset: offset > 0 ? offset : null }, true);
  const clearAll = () =>
    update({ q: null, level: null, procedure: null, min: null, offset: null, ...Object.fromEntries(EXTRA_FILTERS.map(key => [key, null])) }, false);

  return (
    <div>
      {options.error && <ErrorNote error={options.error} onRetry={options.reload} />}
      <PageHead
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
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="f-level">{t("tenders.f_level")}</label>
          <select
            id="f-level"
            value={filters.level}
            onChange={(e) => setFilter({ level: e.target.value || null })}
          >
            <option value="">{t("tenders.f_level_all")}</option>
            <option value="critical">{t("tenders.f_level_critical")}</option>
            <option value="high">{t("tenders.f_level_high")}</option>
            <option value="medium">{t("tenders.f_level_medium")}</option>
            <option value="low">{t("tenders.f_level_low")}</option>
            <option value="unscored">{t("risk.unscored")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-proc">{t("tenders.f_proc")}</label>
          <select
            id="f-proc"
            disabled={procedureOptions.length === 0}
            value={filters.procedure}
            onChange={(e) => setFilter({ procedure: e.target.value || null })}
          >
            <option value="">{t("tenders.f_proc_all")}</option>
            {/* A procedure pasted into the link stays visible even before the
                stats request brings the full option list. */}
            {filters.procedure && !procedureOptions.includes(filters.procedure) && (
              <option value={filters.procedure}>{filters.procedure.replaceAll("_", " ")}</option>
            )}
            {procedureOptions.map((option) => (
              <option key={option} value={option}>{option.replaceAll("_", " ")}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-scored">{t("product.scoreAvailability")}</label>
          <select id="f-scored" value={filters.extra.scored ?? ""} onChange={e => setFilter({ scored: e.target.value })}>
            <option value="">{t("common.all")}</option>
            <option value="true">{t("product.scored")}</option>
            <option value="false">{t("risk.unscored")}</option>
          </select>
        </div>
        {filtered && <button className="ghost" onClick={clearAll}>{t("tenders.clear")}</button>}
      </div>
      <details className="card research-disclosure" open={Object.keys(filters.extra).some(key => key !== "scored") || filters.minRisk > 0 ? true : undefined}>
        <summary>{t("product.moreFilters")}</summary>
        <form className="toolbar" key={JSON.stringify(ADVANCED_FILTERS.map(key => filters.extra[key] ?? ""))} onSubmit={event => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setFilter(Object.fromEntries(ADVANCED_FILTERS.map(key => [key, String(form.get(key) ?? "").trim()])));
        }}>
          {ADVANCED_FILTERS.map(key => (
            <div className="field" key={key}>
              <label htmlFor={key}>{t(`product.${key}`)}</label>
              <input id={key} name={key} defaultValue={filters.extra[key] ?? ""}
                type={key.startsWith("date") ? "date" : key === "cpv" ? "text" : "number"}
                min={key.endsWith("value") ? 0 : undefined} step={key.endsWith("value") ? "any" : undefined}
                pattern={key === "cpv" ? "[0-9]{2,8}(?:-[0-9])?" : undefined} />
            </div>
          ))}
          <button type="submit">{t("product.applyFilters")}</button>
        </form>
        <div className="toolbar">
          <div className="field">
            <label htmlFor="f-risk">{t("tenders.f_risk", { v: filters.minRisk })}</label>
            <input
              id="f-risk"
              type="range"
              min={0}
              max={95}
              step={5}
              value={filters.minRisk}
              onChange={(e) => setFilter({ min: Number(e.target.value) })}
            />
          </div>
        </div>
      </details>

      <RequestPanel
        state={req}
        describe={describe}
        pending={<Skeleton rows={8} height={34} />}
        isEmpty={(result) => result.items.length === 0}
        emptyTitle={t("tenders.empty")}
        emptyHint={filtered ? t("tenders.empty_hint_filtered") : t("tenders.empty_hint")}
        emptyAction={
          filtered ? (
            <button className="ghost" onClick={clearAll}>
              {t("tenders.clear")}
            </button>
          ) : null
        }
      >
        {(result) => (
          <>
            <TableWrap wide>
              <table>
                <caption className="muted" style={{ captionSide: "top", textAlign: "left", padding: "10px 10px 0" }}>
                  {t("tenders.caption", { n: num(result.total) })}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">{t("tenders.th_procedure")}</th>
                    <th scope="col">{t("tenders.th_buyer")}</th>
                    <th scope="col">{t("product.published")}</th>
                    <th scope="col">{t("tenders.th_award")}</th>
                    <th scope="col">{t("tenders.th_priority")}</th>
                    <th scope="col">{t("product.scoreAvailability")}</th>
                    <th scope="col">{t("product.details")}</th>
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((row) => (
                    <tr
                      key={row.tender_id}
                      className="clickable"
                      // Mouse convenience only. The keyboard and screen-reader path
                      // is the real link on the procedure title below, so this row
                      // is not put in the tab order.
                      onClick={(e) => {
                        if ((e.target as HTMLElement).closest("a, button")) return;
                        nav(destination(row.tender_id));
                      }}
                    >
                      <td>
                        <Link to={destination(row.tender_id)}>{row.title ?? t("tenders.untitled")}</Link>
                        <div className="muted mono">{row.tender_id}</div>
                      </td>
                      <td>{row.buyer_name ?? "—"}</td>
                      <td>{dateLabel(row.published_at)}</td>
                      <td className="mono">{row.award_total_mdl == null ? "—" : mdl(row.award_total_mdl)}</td>
                      <td><BandBadge level={row.risk_level} nModels={row.n_models_flagging} /></td>
                      <td>{t(row.risk_score == null ? "risk.unscored" : "product.scored")}</td>
                      <td><Link to={destination(row.tender_id)} aria-label={`${t("product.details")}: ${row.title ?? row.tender_id}`}>{t("product.details")}</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>

          </>
        )}
      </RequestPanel>

      <div className="pager">
        <button
          className="ghost"
          disabled={filters.offset === 0 || req.loading}
          onClick={() => setPage(Math.max(0, filters.offset - PAGE))}
        >
          {t("tenders.prev")}
        </button>
        <span>
          {total === 0 ? "0" : `${filters.offset + 1}–${Math.min(filters.offset + PAGE, total)}`} {t("tenders.of")} {num(total)}
        </span>
        <button
          className="ghost"
          disabled={filters.offset + PAGE >= total || req.loading}
          onClick={() => setPage(filters.offset + PAGE)}
        >
          {t("tenders.next")}
        </button>
      </div>
    </div>
  );
}
