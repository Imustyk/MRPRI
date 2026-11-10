import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getJson, type Tender } from "../api";
import { Empty, ErrorNote, Field, Loading } from "../ui";

export function ProcedurePicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Tender[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [attempt, setAttempt] = useState(0);
  // Once a procedure was chosen by hand, later background search results must
  // never reselect something else behind the analyst's back.
  const manual = useRef(false);
  useEffect(() => {
    let live = true;
    setBusy(true);
    const timer = setTimeout(() => {
      const params = new URLSearchParams({ sort: "risk", limit: "20", q: query.trim() });
      getJson<{ items: Tender[] }>(`/api/tenders?${params}`).then((response) => {
        if (live) { setItems(response.items); setError(null); setBusy(false); }
      }).catch((reason: Error) => { if (live) { setError(reason.message); setBusy(false); } });
    }, 300);
    return () => { live = false; clearTimeout(timer); };
  }, [query, attempt]);
  useEffect(() => {
    // Default selection only: the untouched, unfiltered list, and only while no
    // procedure is selected. A manual pick (or a narrowed search) disables this.
    if (value || manual.current || busy || error || query.trim()) return;
    if (items.length) onChange(items[0].tender_id);
  }, [items, value, onChange, busy, error, query]);
  return (
    <section className="procedure-picker surface" aria-label={t("analysis.select_procedure")}>
      <div className="picker-controls">
        <Field label={t("analysis.find_procedure")} grow><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("analysis.search_hint")} /></Field>
        <Field label={t("analysis.select_procedure")} grow>
          <select value={value} onChange={(event) => { manual.current = true; onChange(event.target.value); }} disabled={busy || items.length === 0}>
            {!items.some((item) => item.tender_id === value) && <option value={value}>{value || t("analysis.select_procedure")}</option>}
            {items.map((item) => <option key={item.tender_id} value={item.tender_id}>{item.title || item.tender_id} · {item.tender_id}</option>)}
          </select>
        </Field>
        {value && <Link className="action-secondary" to={`/tenders/${encodeURIComponent(value)}`}>{t("analysis.open_case")} ↗</Link>}
      </div>
      <p className="microcopy">{t("analysis.picker_scope")}</p>
      {busy && <Loading />}
      {error && <ErrorNote error={error} onRetry={() => setAttempt((n) => n + 1)} />}
      {!busy && !error && !items.length && <Empty title={t("analysis.no_results")} />}
    </section>
  );
}
