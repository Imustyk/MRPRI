import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { intlLocale } from "../i18n";
import { tr } from "../i18n/backendMap";
import {
  addWatchlistItems,
  createAnnotation,
  createCase,
  createView,
  createWatchlist,
  deleteAnnotation,
  deleteCase,
  deleteView,
  deleteWatchlist,
  deleteWatchlistItem,
  getActivity,
  getAnnotations,
  getCase,
  getCases,
  getViews,
  getWatchlist,
  getWatchlists,
  getWorkspaceSummary,
  int,
  updateAnnotation,
  updateCase,
  updateView,
  updateWatchlist,
  type ActivityRecord,
  type AnnotationRecord,
  type CaseRecord,
  type SavedView,
  type WatchItem,
  type Watchlist,
  type WorkspaceSummary,
} from "../api";
import {
  ConfirmButton,
  Empty,
  ErrorNote,
  Field,
  Loading,
  PageHead,
  Panel,
  Pill,
  PriorityPill,
  StatusPill,
  Tabs,
  TableWrap,
  Toast,
} from "../ui";

type TabKey = "cases" | "annotations" | "watchlists" | "views";

/** "2026-09-26T07:08:30+00:00" -> "26 Sep 07:08" */
function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(intlLocale(), {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function actionKey(action: string): string {
  return action.replace(/ /g, "_");
}

export default function Workspace() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabKey>("cases");
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refreshSummary = useCallback(() => {
    getWorkspaceSummary().then(setSummary).catch(() => undefined);
  }, []);

  useEffect(refreshSummary, [refreshSummary]);

  const c = summary?.counts;
  const bump = (msg: string) => {
    setToast(msg);
    refreshSummary();
  };

  return (
    <div>
      <PageHead
        kicker={t("workspace.kicker")}
        title={t("workspace.title")}
        lede={t("workspace.lede")}
      />

      <div className="callout info">{t("workspace.ethics")}</div>

      {c && (
        <div className="grid cards-4" style={{ marginBottom: 16 }}>
          <div className="card">
            <div className="label">{t("workspace.card_cases")}</div>
            <div className="value">{int(c.cases)}</div>
            <div className="note">{t("workspace.card_cases_note")}</div>
          </div>
          <div className="card">
            <div className="label">{t("workspace.card_annot")}</div>
            <div className="value">{int(c.annotations)}</div>
            <div className="note">{t("workspace.card_annot_note")}</div>
          </div>
          <div className="card">
            <div className="label">{t("workspace.card_watch")}</div>
            <div className="value">{int(c.watchlists)}</div>
            <div className="note">{t("workspace.card_watch_note", { n: int(c.watchlist_items) })}</div>
          </div>
          <div className="card">
            <div className="label">{t("workspace.card_views")}</div>
            <div className="value">{int(c.saved_views)}</div>
            <div className="note">{t("workspace.card_views_note")}</div>
          </div>
        </div>
      )}

      <Tabs<TabKey>
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "cases", label: t("workspace.tab_cases"), count: c?.cases },
          { key: "annotations", label: t("workspace.tab_annot"), count: c?.annotations },
          { key: "watchlists", label: t("workspace.tab_watch"), count: c?.watchlists },
          { key: "views", label: t("workspace.tab_views"), count: c?.saved_views },
        ]}
      />

      {tab === "cases" && <CasesTab vocab={summary?.vocab} notify={bump} />}
      {tab === "annotations" && <AnnotationsTab vocab={summary?.vocab} notify={bump} />}
      {tab === "watchlists" && <WatchlistsTab colors={summary?.vocab.watchlist_colors} notify={bump} />}
      {tab === "views" && <ViewsTab notify={bump} />}

      <ActivityFeed />
      <Toast message={toast} onDone={() => setToast(null)} />
    </div>
  );
}

/* ==========================================================================
   Cases
   ========================================================================== */
function CasesTab({
  vocab,
  notify,
}: {
  vocab?: WorkspaceSummary["vocab"];
  notify: (m: string) => void;
}) {
  const { t } = useTranslation();
  const [items, setItems] = useState<CaseRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [form, setForm] = useState({ title: "", priority: "medium", owner: "", summary: "", ocids: "" });

  const load = useCallback(() => {
    setError(null);
    getCases({ status, q })
      .then((d) => setItems(d.items))
      .catch((e: Error) => setError(e.message));
  }, [status, q]);

  useEffect(load, [load]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (form.title.trim().length < 3) {
      setError(t("workspace.err_title_short"));
      return;
    }
    try {
      await createCase({ ...form, ocids: form.ocids });
      setForm({ title: "", priority: "medium", owner: "", summary: "", ocids: "" });
      notify(t("workspace.toast_case_created"));
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <Panel
        title={t("workspace.new_case")}
        note={t("workspace.new_case_p")}
      >
        <form onSubmit={submit}>
          <div className="form-grid">
            <Field label={t("workspace.f_title")} grow>
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder={t("workspace.ph_title")}
                required
                minLength={3}
              />
            </Field>
            <Field label={t("workspace.f_priority")}>
              <select
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value })}
              >
                {(vocab?.case_priority ?? ["low", "medium", "high", "critical"]).map((p) => (
                  <option key={p} value={p}>
                    {tr(p)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("workspace.f_owner")}>
              <input
                value={form.owner}
                onChange={(e) => setForm({ ...form, owner: e.target.value })}
                placeholder={t("workspace.ph_owner")}
              />
            </Field>
            <Field label={t("workspace.f_ocids")} grow>
              <textarea
                value={form.ocids}
                onChange={(e) => setForm({ ...form, ocids: e.target.value })}
                placeholder={"ocds-…\nocds-…"}
                style={{ minHeight: 60 }}
              />
            </Field>
            <Field label={t("workspace.f_summary")} grow>
              <textarea
                value={form.summary}
                onChange={(e) => setForm({ ...form, summary: e.target.value })}
                placeholder={t("workspace.ph_summary")}
                style={{ minHeight: 60 }}
              />
            </Field>
            <div>
              <button type="submit">{t("workspace.btn_create_case")}</button>
            </div>
          </div>
        </form>
      </Panel>

      <Panel
        title={t("workspace.cases_h")}
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label={t("workspace.f_status")}>
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="all">{t("workspace.opt_all")}</option>
                {(vocab?.case_status ?? []).map((s) => (
                  <option key={s} value={s}>
                    {tr(s)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("workspace.f_search")}>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={t("workspace.ph_case_search")}
              />
            </Field>
          </div>
        }
      >
        {error && <ErrorNote error={error} onRetry={load} />}
        {!items ? (
          <Loading label={t("workspace.loading_cases")} />
        ) : items.length === 0 ? (
          <Empty title={t("workspace.empty_cases")} hint={t("workspace.empty_cases_hint")} />
        ) : (
          <TableWrap wide>
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("workspace.th_ref")}</th>
                  <th scope="col">{t("workspace.th_title")}</th>
                  <th scope="col">{t("workspace.th_status")}</th>
                  <th scope="col">{t("workspace.th_priority")}</th>
                  <th scope="col">{t("workspace.th_owner")}</th>
                  <th scope="col">{t("workspace.th_procedures")}</th>
                  <th scope="col">{t("workspace.th_updated")}</th>
                  <th scope="col">{t("workspace.th_actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => {
                  let n = 0;
                  try {
                    n = JSON.parse(r.ocids || "[]").length;
                  } catch {
                    n = 0;
                  }
                  return (
                    <tr key={r.id}>
                      <td className="mono">
                        <button
                          className="ghost small"
                          onClick={() => setOpenId(openId === r.id ? null : r.id)}
                        >
                          {r.ref}
                        </button>
                      </td>
                      <td>{r.title}</td>
                      <td>
                        <StatusPill value={r.status} />
                      </td>
                      <td>
                        <PriorityPill value={r.priority} />
                      </td>
                      <td className="muted">{r.owner || "—"}</td>
                      <td className="mono">{n}</td>
                      <td className="muted mono">{when(r.updated_at)}</td>
                      <td>
                        <span style={{ display: "flex", gap: 6 }}>
                          <StatusEditor
                            value={r.status}
                            options={vocab?.case_status ?? []}
                            onChange={async (v) => {
                              await updateCase(r.id, { status: v });
                              notify(t("workspace.toast_status", { ref: r.ref, status: tr(v) }));
                              load();
                            }}
                          />
                          <ConfirmButton
                            confirmLabel={t("workspace.confirm_delete")}
                            onConfirm={async () => {
                              await deleteCase(r.id);
                              notify(t("workspace.toast_deleted", { ref: r.ref }));
                              load();
                            }}
                          >
                            {t("common.delete")}
                          </ConfirmButton>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableWrap>
        )}
        {openId !== null && <CaseDetail id={openId} onChanged={load} notify={notify} />}
      </Panel>
    </>
  );
}

function StatusEditor({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const [v, setV] = useState(value);
  return (
    <select
      className="small"
      value={v}
      aria-label={t("workspace.change_status")}
      onChange={(e) => {
        setV(e.target.value);
        void onChange(e.target.value);
      }}
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {tr(o)}
        </option>
      ))}
    </select>
  );
}

function CaseDetail({
  id,
  onChanged,
  notify,
}: {
  id: number;
  onChanged: () => void;
  notify: (m: string) => void;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<{ case: CaseRecord; ocids: string[]; annotations: AnnotationRecord[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    getCase(id).then(setData).catch((e: Error) => setError(e.message));
  }, [id]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading label={t("workspace.loading_case")} />;

  return (
    <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--line-soft)" }}>
      <h3>{data.case.ref} · {data.case.title}</h3>
      {data.case.summary && <p className="muted">{data.case.summary}</p>}
      <div className="grid row2">
        <div>
          <h4>{t("workspace.procedures_h", { n: data.ocids.length })}</h4>
          {data.ocids.length === 0 ? (
            <p className="muted">{t("workspace.no_ocids")}</p>
          ) : (
            <TableWrap>
              <table>
                <thead>
                  <tr>
                    <th scope="col">{t("workspace.th_ocid")}</th>
                    <th scope="col">{t("workspace.th_notes")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.ocids.map((o) => (
                    <tr key={o}>
                      <td className="mono" style={{ fontSize: 12 }}>
                        {o}
                      </td>
                      <td>
                        {data.annotations.filter((a) => a.ocid === o).length > 0 ? (
                          data.annotations
                            .filter((a) => a.ocid === o)
                            .map((a) => (
                              <div key={a.id} className="muted" style={{ fontSize: 12.5 }}>
                                <Pill tone="info">{tr(a.category)}</Pill> {a.note}
                              </div>
                            ))
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </div>
        <div>
          <h4>{t("workspace.add_note_h")}</h4>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t("workspace.ph_case_note")}
          />
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <select
              aria-label={t("workspace.which_procedure")}
              style={{ maxWidth: 210 }}
              defaultValue={data.ocids[0] ?? ""}
              id={`ocid-${id}`}
            >
              {data.ocids.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
            <button
              className="small"
              disabled={!note.trim()}
              onClick={async () => {
                const ocid = (document.getElementById(`ocid-${id}`) as HTMLSelectElement)?.value;
                if (!ocid) return;
                try {
                  await createAnnotation({ ocid, note, case_id: id });
                  setNote("");
                  notify(t("workspace.toast_note_added"));
                  onChanged();
                  const fresh = await getCase(id);
                  if (fresh) setData(fresh);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              {t("workspace.btn_add_note")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ==========================================================================
   Annotations
   ========================================================================== */
function AnnotationsTab({
  vocab,
  notify,
}: {
  vocab?: WorkspaceSummary["vocab"];
  notify: (m: string) => void;
}) {
  const { t } = useTranslation();
  const [items, setItems] = useState<AnnotationRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState("all");
  const [q, setQ] = useState("");
  const [draft, setDraft] = useState({ ocid: "", note: "", category: "observation", author: "" });
  const [editing, setEditing] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  const load = useCallback(() => {
    setError(null);
    getAnnotations({ category, q })
      .then((d) => setItems(d.items))
      .catch((e: Error) => setError(e.message));
  }, [category, q]);

  useEffect(load, [load]);

  return (
    <>
      <Panel title={t("workspace.new_annot")} note={t("workspace.new_annot_p")}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await createAnnotation(draft);
              setDraft({ ocid: "", note: "", category: "observation", author: draft.author });
              notify(t("workspace.toast_annot_added"));
              load();
            } catch (err) {
              setError((err as Error).message);
            }
          }}
        >
          <div className="form-grid">
            <Field label={t("workspace.f_ocid")} grow>
              <input
                value={draft.ocid}
                onChange={(e) => setDraft({ ...draft, ocid: e.target.value })}
                placeholder="ocds-…"
                required
              />
            </Field>
            <Field label={t("workspace.f_category")}>
              <select
                value={draft.category}
                onChange={(e) => setDraft({ ...draft, category: e.target.value })}
              >
                {(vocab?.annotation_category ?? []).map((k) => (
                  <option key={k} value={k}>
                    {tr(k)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("workspace.f_author")}>
              <input
                value={draft.author}
                onChange={(e) => setDraft({ ...draft, author: e.target.value })}
              />
            </Field>
            <Field label={t("workspace.f_note")} grow>
              <input
                value={draft.note}
                onChange={(e) => setDraft({ ...draft, note: e.target.value })}
                placeholder={t("workspace.ph_annot_note")}
                required
              />
            </Field>
            <div>
              <button type="submit">{t("workspace.btn_add_note")}</button>
            </div>
          </div>
        </form>
      </Panel>

      <Panel
        title={t("workspace.annot_h")}
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label={t("workspace.f_category")}>
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="all">{t("workspace.opt_all")}</option>
                {(vocab?.annotation_category ?? []).map((k) => (
                  <option key={k} value={k}>
                    {tr(k)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("workspace.f_search")}>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder={t("workspace.ph_annot_search")}
              />
            </Field>
          </div>
        }
      >
        {error && <ErrorNote error={error} onRetry={load} />}
        {!items ? (
          <Loading label={t("workspace.loading_annot")} />
        ) : items.length === 0 ? (
          <Empty
            title={t("workspace.empty_annot")}
            hint={t("workspace.empty_annot_hint")}
          />
        ) : (
          <TableWrap wide>
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("workspace.th_ocid")}</th>
                  <th scope="col">{t("workspace.th_category")}</th>
                  <th scope="col">{t("workspace.th_note")}</th>
                  <th scope="col">{t("workspace.th_case")}</th>
                  <th scope="col">{t("workspace.th_author")}</th>
                  <th scope="col">{t("workspace.th_updated")}</th>
                  <th scope="col">{t("workspace.th_actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id}>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {r.ocid}
                    </td>
                    <td>
                      <Pill tone="info">{tr(r.category)}</Pill>
                    </td>
                    <td>
                      {editing === r.id ? (
                        <span style={{ display: "flex", gap: 6 }}>
                          <input
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            autoFocus
                          />
                          <button
                            className="small"
                            onClick={async () => {
                              await updateAnnotation(r.id, { note: editText });
                              setEditing(null);
                              notify(t("workspace.toast_note_updated"));
                              load();
                            }}
                          >
                            {t("common.save")}
                          </button>
                          <button className="ghost small" onClick={() => setEditing(null)}>
                            {t("common.cancel")}
                          </button>
                        </span>
                      ) : (
                        r.note
                      )}
                    </td>
                    <td className="muted">{r.case_ref ?? "—"}</td>
                    <td className="muted">{r.author || "—"}</td>
                    <td className="muted mono">{when(r.updated_at)}</td>
                    <td>
                      <span style={{ display: "flex", gap: 6 }}>
                        <button
                          className="ghost small"
                          onClick={() => {
                            setEditing(r.id);
                            setEditText(r.note);
                          }}
                        >
                          {t("common.edit")}
                        </button>
                        <ConfirmButton
                          confirmLabel={t("workspace.confirm_delete")}
                          onConfirm={async () => {
                            await deleteAnnotation(r.id);
                            notify(t("workspace.toast_annot_deleted"));
                            load();
                          }}
                        >
                          {t("common.delete")}
                        </ConfirmButton>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Panel>
    </>
  );
}

/* ==========================================================================
   Watchlists
   ========================================================================== */
function WatchlistsTab({
  colors,
  notify,
}: {
  colors?: Record<string, string>;
  notify: (m: string) => void;
}) {
  const { t } = useTranslation();
  const [lists, setLists] = useState<Watchlist[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [items, setItems] = useState<WatchItem[] | null>(null);
  const [draft, setDraft] = useState({ name: "", description: "", color: "navy" });
  const [ocids, setOcids] = useState("");

  const palette = colors ?? { navy: "#1e3a5f", gold: "#b8892a", red: "#b4232c", green: "#2a6b4a", teal: "#2a7f8f", plum: "#6b4a86" };

  const load = useCallback(() => {
    getWatchlists()
      .then((d) => {
        setLists(d.items);
        setSelected((s) => s ?? d.items[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    if (selected === null) {
      setItems(null);
      return;
    }
    getWatchlist(selected)
      .then((d) => setItems(d.items))
      .catch((e: Error) => setError(e.message));
  }, [selected]);

  return (
    <>
      <Panel title={t("workspace.new_watch")} note={t("workspace.new_watch_p")}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await createWatchlist(draft);
              setDraft({ name: "", description: "", color: "navy" });
              notify(t("workspace.toast_watch_created"));
              load();
            } catch (err) {
              setError((err as Error).message);
            }
          }}
        >
          <div className="form-grid">
            <Field label={t("workspace.f_name")} grow>
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder={t("workspace.ph_watch_name")}
                required
              />
            </Field>
            <Field label={t("workspace.f_colour")}>
              <select
                value={draft.color}
                onChange={(e) => setDraft({ ...draft, color: e.target.value })}
              >
                {Object.keys(palette).map((k) => (
                  <option key={k} value={k}>
                    {t(`workspace.color.${k}`)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label={t("workspace.f_description")} grow>
              <input
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            </Field>
            <div>
              <button type="submit">{t("common.create")}</button>
            </div>
          </div>
        </form>
      </Panel>

      <div className="grid row2">
        <Panel title={t("workspace.watch_h")}>
          {error && <ErrorNote error={error} onRetry={load} />}
          {!lists ? (
            <Loading />
          ) : lists.length === 0 ? (
            <Empty title={t("workspace.empty_watch")} />
          ) : (
            <TableWrap>
              <table>
                <thead>
                  <tr>
                    <th scope="col">{t("workspace.th_name")}</th>
                    <th scope="col">{t("workspace.th_items")}</th>
                    <th scope="col">{t("workspace.th_actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {lists.map((w) => (
                    <tr
                      key={w.id}
                      className="clickable"
                      onClick={() => setSelected(w.id)}
                      style={selected === w.id ? { background: "#f8f1e3" } : undefined}
                    >
                      <td>
                        <span className="swatch" style={{ background: palette[w.color] ?? w.color }} />{" "}
                        {w.name}
                        {w.description && <div className="muted" style={{ fontSize: 12 }}>{w.description}</div>}
                      </td>
                      <td className="mono">{int(w.n_items)}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <span style={{ display: "flex", gap: 6 }}>
                          <select
                            className="small"
                            aria-label={t("workspace.recolour", { name: w.name })}
                            value={w.color}
                            onChange={async (e) => {
                              await updateWatchlist(w.id, { color: e.target.value });
                              notify(t("workspace.toast_recoloured", { name: w.name }));
                              load();
                            }}
                          >
                            {Object.keys(palette).map((k) => (
                              <option key={k} value={k}>
                                {t(`workspace.color.${k}`)}
                              </option>
                            ))}
                          </select>
                          <ConfirmButton
                            confirmLabel={t("workspace.confirm_delete")}
                            onConfirm={async () => {
                              await deleteWatchlist(w.id);
                              if (selected === w.id) setSelected(null);
                              notify(t("workspace.toast_watch_deleted", { name: w.name }));
                              load();
                            }}
                          >
                            {t("common.delete")}
                          </ConfirmButton>
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
        </Panel>

        <Panel title={t("workspace.items_h")} note={t("workspace.items_p")}>
          {selected === null ? (
            <Empty title={t("workspace.select_watch")} />
          ) : (
            <>
              <textarea
                value={ocids}
                onChange={(e) => setOcids(e.target.value)}
                placeholder={"ocds-…\nocds-…"}
                style={{ minHeight: 64 }}
              />
              <div style={{ marginTop: 8 }}>
                <button
                  className="small"
                  disabled={!ocids.trim()}
                  onClick={async () => {
                    try {
                      const r = await addWatchlistItems(selected, ocids);
                      setOcids("");
                      notify(
                        r.added === 0
                          ? t("workspace.toast_nothing_added")
                          : t("workspace.toast_added", { count: r.added }),
                      );
                      setItems(r.items);
                      load();
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  {t("workspace.btn_add_ocids")}
                </button>
              </div>
              <div style={{ marginTop: 14 }}>
                {!items ? (
                  <Loading />
                ) : items.length === 0 ? (
                  <Empty title={t("workspace.empty_items")} hint={t("workspace.empty_items_hint")} />
                ) : (
                  <TableWrap>
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">{t("workspace.th_ocid")}</th>
                          <th scope="col">{t("workspace.th_added")}</th>
                          <th scope="col" />
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((it) => (
                          <tr key={it.id}>
                            <td className="mono" style={{ fontSize: 12 }}>
                              {it.ocid}
                            </td>
                            <td className="muted mono">{when(it.added_at)}</td>
                            <td>
                              <ConfirmButton
                                confirmLabel={t("workspace.confirm_remove")}
                                onConfirm={async () => {
                                  await deleteWatchlistItem(it.id);
                                  notify(t("workspace.toast_removed"));
                                  getWatchlist(selected)
                                    .then((d) => setItems(d.items))
                                    .catch(() => undefined);
                                  load();
                                }}
                              >
                                {t("workspace.btn_remove")}
                              </ConfirmButton>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                )}
              </div>
            </>
          )}
        </Panel>
      </div>
    </>
  );
}

/* ==========================================================================
   Saved views
   ========================================================================== */
function ViewsTab({ notify }: { notify: (m: string) => void }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<SavedView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ name: "", description: "", payload: "" });
  const [editing, setEditing] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  const load = useCallback(() => {
    getViews()
      .then((d) => setItems(d.items))
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  const parsed = useMemo(() => {
    if (!draft.payload.trim()) return null;
    try {
      return { ok: true as const, value: JSON.parse(draft.payload) as unknown };
    } catch (e) {
      return { ok: false as const, error: (e as Error).message };
    }
  }, [draft.payload]);

  return (
    <>
      <Panel title={t("workspace.new_view")} note={t("workspace.new_view_p")}>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (draft.payload.trim() && !parsed?.ok) {
              setError(t("api.bad_json", { err: parsed?.error }));
              return;
            }
            try {
              await createView({
                name: draft.name,
                description: draft.description,
                payload: (parsed?.ok ? parsed.value : {}) as Record<string, unknown>,
              });
              setDraft({ name: "", description: "", payload: "" });
              notify(t("workspace.toast_view_saved"));
              load();
            } catch (err) {
              setError((err as Error).message);
            }
          }}
        >
          <div className="form-grid">
            <Field label={t("workspace.f_name")} grow>
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder={t("workspace.ph_view_name")}
                required
              />
            </Field>
            <Field label={t("workspace.f_description")} grow>
              <input
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            </Field>
            <Field
              label={t("workspace.f_payload")}
              grow
              hint={
                parsed?.ok
                  ? t("workspace.json_ok")
                  : draft.payload
                    ? t("workspace.json_bad")
                    : t("workspace.json_optional")
              }
            >
              <textarea
                value={draft.payload}
                onChange={(e) => setDraft({ ...draft, payload: e.target.value })}
                placeholder='{"level": "critical", "min_value": 1000000}'
                style={{ minHeight: 60, fontFamily: "IBM Plex Mono, monospace", fontSize: 12.5 }}
              />
            </Field>
            <div>
              <button type="submit">{t("workspace.btn_save_view")}</button>
            </div>
          </div>
        </form>
      </Panel>

      <Panel title={t("workspace.views_h")}>
        {error && <ErrorNote error={error} onRetry={load} />}
        {!items ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty title={t("workspace.empty_views")} />
        ) : (
          <TableWrap wide>
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("workspace.th_name")}</th>
                  <th scope="col">{t("workspace.f_description")}</th>
                  <th scope="col">{t("workspace.th_payload")}</th>
                  <th scope="col">{t("workspace.th_updated")}</th>
                  <th scope="col">{t("workspace.th_actions")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((v) => (
                  <tr key={v.id}>
                    <td>{v.name}</td>
                    <td className="muted">{v.description || "—"}</td>
                    <td style={{ maxWidth: 320 }}>
                      {editing === v.id ? (
                        <span style={{ display: "flex", gap: 6 }}>
                          <input
                            value={editText}
                            onChange={(e) => setEditText(e.target.value)}
                            autoFocus
                          />
                          <button
                            className="small"
                            onClick={async () => {
                              try {
                                const parsedEdit = JSON.parse(editText) as Record<string, unknown>;
                                await updateView(v.id, { payload: parsedEdit });
                                setEditing(null);
                                notify(t("workspace.toast_view_updated"));
                                load();
                              } catch (err) {
                                setError((err as Error).message);
                              }
                            }}
                          >
                            {t("common.save")}
                          </button>
                          <button className="ghost small" onClick={() => setEditing(null)}>
                            {t("common.cancel")}
                          </button>
                        </span>
                      ) : (
                        <code style={{ fontSize: 11.5, wordBreak: "break-all" }}>{v.payload}</code>
                      )}
                    </td>
                    <td className="muted mono">{when(v.updated_at)}</td>
                    <td>
                      <span style={{ display: "flex", gap: 6 }}>
                        <button
                          className="ghost small"
                          onClick={() => {
                            setEditing(v.id);
                            setEditText(v.payload);
                          }}
                        >
                          {t("common.edit")}
                        </button>
                        <ConfirmButton
                          confirmLabel={t("workspace.confirm_delete")}
                          onConfirm={async () => {
                            await deleteView(v.id);
                            notify(t("workspace.toast_view_deleted"));
                            load();
                          }}
                        >
                          {t("common.delete")}
                        </ConfirmButton>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Panel>
    </>
  );
}

/* ==========================================================================
   Activity
   ========================================================================== */
function ActivityFeed() {
  const { t } = useTranslation();
  const [items, setItems] = useState<ActivityRecord[] | null>(null);
  useEffect(() => {
    getActivity(20)
      .then((d) => setItems(d.items))
      .catch(() => setItems([]));
  }, []);
  if (!items || items.length === 0) return null;
  return (
    <Panel title={t("workspace.activity_h")} note={t("workspace.activity_p")}>
      <TableWrap>
        <table>
          <thead>
            <tr>
              <th scope="col">{t("workspace.th_when")}</th>
              <th scope="col">{t("workspace.th_entity")}</th>
              <th scope="col">{t("workspace.th_action")}</th>
              <th scope="col">{t("workspace.th_detail")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td className="muted mono">{when(a.at)}</td>
                <td>{t(`workspace.entity.${a.entity}`, { defaultValue: a.entity })}</td>
                <td>
                  <Pill
                    tone={
                      a.action === "delete" ? "risk" : a.action === "create" ? "ok" : "info"
                    }
                  >
                    {t(`workspace.action.${actionKey(a.action)}`, {
                      defaultValue: a.action,
                    })}
                  </Pill>
                </td>
                <td className="muted">{a.detail || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </Panel>
  );
}
