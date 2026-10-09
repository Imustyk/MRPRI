import { useCallback, useEffect, useMemo, useState } from "react";
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
  return d.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function Workspace() {
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
      <div className="kicker">Analyst workspace</div>
      <h1>Cases, notes &amp; watchlists</h1>
      <p className="lede">
        Everything on this page is analyst work product, stored separately in SQLite so the
        research pipeline output stays read-only and reproducible. Cases group the procedures
        under investigation, annotations record what was checked, and watchlists hold the OCIDs
        worth returning to.
      </p>

      <div className="callout info">
        A risk band is a signal, not a finding. Workspace entries are working notes about
        published procurement data — they are not accusations, and nothing here should be
        presented as a determination of corruption.
      </div>

      {c && (
        <div className="grid cards-4" style={{ marginBottom: 16 }}>
          <div className="card">
            <div className="label">Cases</div>
            <div className="value">{int(c.cases)}</div>
            <div className="note">investigation files</div>
          </div>
          <div className="card">
            <div className="label">Annotations</div>
            <div className="value">{int(c.annotations)}</div>
            <div className="note">notes on procedures</div>
          </div>
          <div className="card">
            <div className="label">Watchlists</div>
            <div className="value">{int(c.watchlists)}</div>
            <div className="note">{int(c.watchlist_items)} procedures tracked</div>
          </div>
          <div className="card">
            <div className="label">Saved views</div>
            <div className="value">{int(c.saved_views)}</div>
            <div className="note">reusable filter sets</div>
          </div>
        </div>
      )}

      <Tabs<TabKey>
        active={tab}
        onChange={setTab}
        tabs={[
          { key: "cases", label: "Cases", count: c?.cases },
          { key: "annotations", label: "Annotations", count: c?.annotations },
          { key: "watchlists", label: "Watchlists", count: c?.watchlists },
          { key: "views", label: "Saved views", count: c?.saved_views },
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
      setError("A case needs a title of at least 3 characters.");
      return;
    }
    try {
      await createCase({ ...form, ocids: form.ocids });
      setForm({ title: "", priority: "medium", owner: "", summary: "", ocids: "" });
      notify("Case created");
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <Panel
        title="New case"
        note="A case groups the procedures under investigation. OCIDs can be pasted as a list, one per line or separated by commas."
      >
        <form onSubmit={submit}>
          <div className="form-grid">
            <Field label="Title" grow>
              <input
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="Repeat awards to a single supplier"
                required
                minLength={3}
              />
            </Field>
            <Field label="Priority">
              <select
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: e.target.value })}
              >
                {(vocab?.case_priority ?? ["low", "medium", "high", "critical"]).map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Owner">
              <input
                value={form.owner}
                onChange={(e) => setForm({ ...form, owner: e.target.value })}
                placeholder="analyst"
              />
            </Field>
            <Field label="Procedures (OCIDs)" grow>
              <textarea
                value={form.ocids}
                onChange={(e) => setForm({ ...form, ocids: e.target.value })}
                placeholder={"ocds-…\nocds-…"}
                style={{ minHeight: 60 }}
              />
            </Field>
            <Field label="Summary" grow>
              <textarea
                value={form.summary}
                onChange={(e) => setForm({ ...form, summary: e.target.value })}
                placeholder="What prompted this case, and what needs checking"
                style={{ minHeight: 60 }}
              />
            </Field>
            <div>
              <button type="submit">Create case</button>
            </div>
          </div>
        </form>
      </Panel>

      <Panel
        title="Cases"
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label="Status">
              <select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="all">all</option>
                {(vocab?.case_status ?? []).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Search">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="title, ref, owner…"
              />
            </Field>
          </div>
        }
      >
        {error && <ErrorNote error={error} onRetry={load} />}
        {!items ? (
          <Loading label="Loading cases…" />
        ) : items.length === 0 ? (
          <Empty title="No cases yet" hint="Create one above, or clear the status filter." />
        ) : (
          <TableWrap wide>
            <table>
              <thead>
                <tr>
                  <th scope="col">Ref</th>
                  <th scope="col">Title</th>
                  <th scope="col">Status</th>
                  <th scope="col">Priority</th>
                  <th scope="col">Owner</th>
                  <th scope="col">Procedures</th>
                  <th scope="col">Updated</th>
                  <th scope="col">Actions</th>
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
                              notify(`${r.ref} → ${v}`);
                              load();
                            }}
                          />
                          <ConfirmButton
                            confirmLabel="Delete?"
                            onConfirm={async () => {
                              await deleteCase(r.id);
                              notify(`${r.ref} deleted`);
                              load();
                            }}
                          >
                            Delete
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
  const [v, setV] = useState(value);
  return (
    <select
      className="small"
      value={v}
      aria-label="Change status"
      onChange={(e) => {
        setV(e.target.value);
        void onChange(e.target.value);
      }}
    >
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
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
  const [data, setData] = useState<{ case: CaseRecord; ocids: string[]; annotations: AnnotationRecord[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    getCase(id).then(setData).catch((e: Error) => setError(e.message));
  }, [id]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading label="Loading case…" />;

  return (
    <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--line-soft)" }}>
      <h3>{data.case.ref} · {data.case.title}</h3>
      {data.case.summary && <p className="muted">{data.case.summary}</p>}
      <div className="grid row2">
        <div>
          <h4>Procedures ({data.ocids.length})</h4>
          {data.ocids.length === 0 ? (
            <p className="muted">No OCIDs linked to this case.</p>
          ) : (
            <TableWrap>
              <table>
                <thead>
                  <tr>
                    <th scope="col">OCID</th>
                    <th scope="col">Notes</th>
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
                                <Pill tone="info">{a.category}</Pill> {a.note}
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
          <h4>Add a note</h4>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What was checked, and what it showed"
          />
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <select
              aria-label="Which procedure"
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
                  notify("Note added");
                  onChanged();
                  const fresh = await getCase(id);
                  if (fresh) setData(fresh);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Add note
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
      <Panel title="New annotation" note="A note attached to one procedure OCID.">
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await createAnnotation(draft);
              setDraft({ ocid: "", note: "", category: "observation", author: draft.author });
              notify("Annotation added");
              load();
            } catch (err) {
              setError((err as Error).message);
            }
          }}
        >
          <div className="form-grid">
            <Field label="OCID" grow>
              <input
                value={draft.ocid}
                onChange={(e) => setDraft({ ...draft, ocid: e.target.value })}
                placeholder="ocds-…"
                required
              />
            </Field>
            <Field label="Category">
              <select
                value={draft.category}
                onChange={(e) => setDraft({ ...draft, category: e.target.value })}
              >
                {(vocab?.annotation_category ?? []).map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Author">
              <input
                value={draft.author}
                onChange={(e) => setDraft({ ...draft, author: e.target.value })}
              />
            </Field>
            <Field label="Note" grow>
              <input
                value={draft.note}
                onChange={(e) => setDraft({ ...draft, note: e.target.value })}
                placeholder="What this shows"
                required
              />
            </Field>
            <div>
              <button type="submit">Add note</button>
            </div>
          </div>
        </form>
      </Panel>

      <Panel
        title="Annotations"
        actions={
          <div className="toolbar" style={{ margin: 0 }}>
            <Field label="Category">
              <select value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="all">all</option>
                {(vocab?.annotation_category ?? []).map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Search">
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="note or OCID…" />
            </Field>
          </div>
        }
      >
        {error && <ErrorNote error={error} onRetry={load} />}
        {!items ? (
          <Loading label="Loading annotations…" />
        ) : items.length === 0 ? (
          <Empty title="No annotations" hint="Notes added here or from a case appear in this list." />
        ) : (
          <TableWrap wide>
            <table>
              <thead>
                <tr>
                  <th scope="col">OCID</th>
                  <th scope="col">Category</th>
                  <th scope="col">Note</th>
                  <th scope="col">Case</th>
                  <th scope="col">Author</th>
                  <th scope="col">Updated</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id}>
                    <td className="mono" style={{ fontSize: 12 }}>
                      {r.ocid}
                    </td>
                    <td>
                      <Pill tone="info">{r.category}</Pill>
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
                              notify("Note updated");
                              load();
                            }}
                          >
                            Save
                          </button>
                          <button className="ghost small" onClick={() => setEditing(null)}>
                            Cancel
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
                          Edit
                        </button>
                        <ConfirmButton
                          confirmLabel="Delete?"
                          onConfirm={async () => {
                            await deleteAnnotation(r.id);
                            notify("Annotation deleted");
                            load();
                          }}
                        >
                          Delete
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
      <Panel title="New watchlist" note="A named collection of procedures to keep an eye on.">
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await createWatchlist(draft);
              setDraft({ name: "", description: "", color: "navy" });
              notify("Watchlist created");
              load();
            } catch (err) {
              setError((err as Error).message);
            }
          }}
        >
          <div className="form-grid">
            <Field label="Name" grow>
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="Mega suppliers"
                required
              />
            </Field>
            <Field label="Colour">
              <select
                value={draft.color}
                onChange={(e) => setDraft({ ...draft, color: e.target.value })}
              >
                {Object.keys(palette).map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Description" grow>
              <input
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            </Field>
            <div>
              <button type="submit">Create</button>
            </div>
          </div>
        </form>
      </Panel>

      <div className="grid row2">
        <Panel title="Watchlists">
          {error && <ErrorNote error={error} onRetry={load} />}
          {!lists ? (
            <Loading />
          ) : lists.length === 0 ? (
            <Empty title="No watchlists yet" />
          ) : (
            <TableWrap>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Name</th>
                    <th scope="col">Items</th>
                    <th scope="col">Actions</th>
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
                            aria-label={`Recolour ${w.name}`}
                            value={w.color}
                            onChange={async (e) => {
                              await updateWatchlist(w.id, { color: e.target.value });
                              notify(`${w.name} recoloured`);
                              load();
                            }}
                          >
                            {Object.keys(palette).map((k) => (
                              <option key={k} value={k}>
                                {k}
                              </option>
                            ))}
                          </select>
                          <ConfirmButton
                            confirmLabel="Delete?"
                            onConfirm={async () => {
                              await deleteWatchlist(w.id);
                              if (selected === w.id) setSelected(null);
                              notify(`${w.name} deleted`);
                              load();
                            }}
                          >
                            Delete
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

        <Panel
          title="Items"
          note="Paste OCIDs to add several at once. Duplicates already on the list are ignored."
        >
          {selected === null ? (
            <Empty title="Select a watchlist" />
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
                      notify(r.added === 0 ? "Nothing added — all already listed" : `${r.added} added`);
                      setItems(r.items);
                      load();
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  Add OCIDs
                </button>
              </div>
              <div style={{ marginTop: 14 }}>
                {!items ? (
                  <Loading />
                ) : items.length === 0 ? (
                  <Empty title="Empty" hint="Nothing tracked here yet." />
                ) : (
                  <TableWrap>
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">OCID</th>
                          <th scope="col">Added</th>
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
                                confirmLabel="Remove?"
                                onConfirm={async () => {
                                  await deleteWatchlistItem(it.id);
                                  notify("Removed from watchlist");
                                  getWatchlist(selected)
                                    .then((d) => setItems(d.items))
                                    .catch(() => undefined);
                                  load();
                                }}
                              >
                                Remove
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
      <Panel
        title="New saved view"
        note="A named filter configuration, stored as JSON so the same slice of the data can be recalled exactly."
      >
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (draft.payload.trim() && !parsed?.ok) {
              setError(`Payload is not valid JSON: ${parsed?.error}`);
              return;
            }
            try {
              await createView({
                name: draft.name,
                description: draft.description,
                payload: (parsed?.ok ? parsed.value : {}) as Record<string, unknown>,
              });
              setDraft({ name: "", description: "", payload: "" });
              notify("View saved");
              load();
            } catch (err) {
              setError((err as Error).message);
            }
          }}
        >
          <div className="form-grid">
            <Field label="Name" grow>
              <input
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="High value, open tender"
                required
              />
            </Field>
            <Field label="Description" grow>
              <input
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
              />
            </Field>
            <Field
              label="Payload (JSON)"
              grow
              hint={parsed?.ok ? "Valid JSON." : draft.payload ? "Not valid JSON yet." : "Optional."}
            >
              <textarea
                value={draft.payload}
                onChange={(e) => setDraft({ ...draft, payload: e.target.value })}
                placeholder='{"level": "critical", "min_value": 1000000}'
                style={{ minHeight: 60, fontFamily: "IBM Plex Mono, monospace", fontSize: 12.5 }}
              />
            </Field>
            <div>
              <button type="submit">Save view</button>
            </div>
          </div>
        </form>
      </Panel>

      <Panel title="Saved views">
        {error && <ErrorNote error={error} onRetry={load} />}
        {!items ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty title="No saved views" />
        ) : (
          <TableWrap wide>
            <table>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Description</th>
                  <th scope="col">Payload</th>
                  <th scope="col">Updated</th>
                  <th scope="col">Actions</th>
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
                                notify("View updated");
                                load();
                              } catch (err) {
                                setError((err as Error).message);
                              }
                            }}
                          >
                            Save
                          </button>
                          <button className="ghost small" onClick={() => setEditing(null)}>
                            Cancel
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
                          Edit
                        </button>
                        <ConfirmButton
                          confirmLabel="Delete?"
                          onConfirm={async () => {
                            await deleteView(v.id);
                            notify("View deleted");
                            load();
                          }}
                        >
                          Delete
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
  const [items, setItems] = useState<ActivityRecord[] | null>(null);
  useEffect(() => {
    getActivity(20)
      .then((d) => setItems(d.items))
      .catch(() => setItems([]));
  }, []);
  if (!items || items.length === 0) return null;
  return (
    <Panel title="Recent workspace activity" note="Every create, update and delete is recorded, so the working history survives a session.">
      <TableWrap>
        <table>
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Entity</th>
              <th scope="col">Action</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td className="muted mono">{when(a.at)}</td>
                <td>{a.entity}</td>
                <td>
                  <Pill
                    tone={
                      a.action === "delete" ? "risk" : a.action === "create" ? "ok" : "info"
                    }
                  >
                    {a.action}
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
