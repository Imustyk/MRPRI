import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import {
  PHASES,
  ROLES,
  TASKS,
  WORKLOAD,
  LETTER_MEANING,
  type PhaseId,
  type RaciLetter,
  type RoleCode,
  hasLetter,
  lettersOf,
} from "../data/raci";
import { MiniStats, PageHead, Pill, TableWrap } from "../ui";

const ROLE_CODES: RoleCode[] = ["SD", "SS", "DE", "TR", "DP", "AI"];

function cellClass(letter: RaciLetter, dim: boolean): string {
  if (!letter) return `raci-cell vacant${dim ? " dim" : ""}`;
  const key = letter === "A/R" ? "ar" : letter.toLowerCase();
  return `raci-cell ${key}${dim ? " dim" : ""}`;
}

/** "A/R" -> "AR", so it can be used as an i18n key segment. */
const letterKey = (l: string) => (l === "A/R" ? "AR" : l);

export default function Raci() {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<PhaseId | "all">("all");
  const [focus, setFocus] = useState<RoleCode | null>(null);
  const [ownOnly, setOwnOnly] = useState(false);
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return TASKS.filter((task) => {
      if (phase !== "all" && task.phase !== phase) return false;
      if (
        ownOnly &&
        focus &&
        !hasLetter(lettersOf(task, focus), "A") &&
        !hasLetter(lettersOf(task, focus), "R")
      ) {
        return false;
      }
      if (!needle) return true;
      // Search the localised text and the artefact path, so a query in either
      // language finds the task.
      const localised = t(`raci.task.${task.id}`).toLowerCase();
      return (
        task.id.toLowerCase().includes(needle) ||
        localised.includes(needle) ||
        task.artefact.toLowerCase().includes(needle)
      );
    });
  }, [phase, ownOnly, focus, q, t]);

  const grouped = useMemo(() => {
    return PHASES.map((p) => ({
      ...p,
      tasks: rows.filter((task) => task.phase === p.id),
    })).filter((p) => p.tasks.length > 0);
  }, [rows]);

  const maxLoad = Math.max(...WORKLOAD.map((w) => w.total));

  return (
    <div>
      <PageHead kicker={t("raci.kicker")} title={t("raci.title")} lede={t("raci.lede")} />

      <div className="callout info">
        <Trans i18nKey="raci.callout" components={{ code: <code /> }} />
      </div>

      <MiniStats
        items={[
          { label: t("raci.stat_tasks"), value: "35", tone: "ok" },
          { label: t("raci.stat_analyst_a"), value: "24", tone: "warn" },
          { label: t("raci.stat_supervisor_a"), value: "11" },
          { label: t("raci.stat_expert_r"), value: "0", tone: "risk" },
        ]}
      />

      <div className="raci-roles">
        {ROLES.map((r) => (
          <button
            key={r.code}
            type="button"
            className={`role-card${focus === r.code ? " active" : ""}`}
            onClick={() => setFocus((cur) => (cur === r.code ? null : r.code))}
            aria-pressed={focus === r.code}
          >
            <span className="role-code">{r.code}</span>
            <strong>{t(`raci.role.${r.code}.name`)}</strong>
            <span className="muted">{t(`raci.role.${r.code}.basis`)}</span>
            {r.external && <Pill tone="warn">{t("raci.external")}</Pill>}
          </button>
        ))}
      </div>

      <div className="raci-legend">
        {Object.keys(LETTER_MEANING).map((k) => (
          <span key={k} className="raci-legend-item">
            <span className={cellClass(k as RaciLetter, false)}>{k}</span>
            {t(`raci.letter_${letterKey(k)}`)}
          </span>
        ))}
      </div>

      <div className="toolbar raci-toolbar">
        <div className="field grow">
          <label htmlFor="raci-q">{t("raci.f_search")}</label>
          <input
            id="raci-q"
            type="search"
            placeholder={t("raci.f_search_ph")}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="raci-phase">{t("raci.f_phase")}</label>
          <select
            id="raci-phase"
            value={phase}
            onChange={(e) => setPhase(e.target.value as PhaseId | "all")}
          >
            <option value="all">{t("raci.f_phase_all")}</option>
            {PHASES.map((p) => (
              <option key={p.id} value={p.id}>
                {p.id}. {t(`raci.phase.${p.id}`)}
              </option>
            ))}
          </select>
        </div>
        <label className="raci-toggle">
          <input
            type="checkbox"
            checked={ownOnly}
            disabled={!focus}
            onChange={(e) => setOwnOnly(e.target.checked)}
          />
          {t("raci.f_own", {
            role: focus ? t(`raci.role.${focus}.short`) : t("raci.f_own_none"),
          })}
        </label>
        {(q || phase !== "all" || ownOnly || focus) && (
          <button
            className="ghost"
            type="button"
            onClick={() => {
              setQ("");
              setPhase("all");
              setOwnOnly(false);
              setFocus(null);
            }}
          >
            {t("raci.reset")}
          </button>
        )}
      </div>

      {focus && (
        <p className="panel-note" style={{ marginBottom: 12 }}>
          <Trans
            i18nKey="raci.focus_note"
            values={{ role: t(`raci.role.${focus}.name`) }}
            components={{ strong: <strong /> }}
          />
        </p>
      )}

      {rows.length === 0 ? (
        <div className="empty">
          <p className="empty-title">{t("raci.empty")}</p>
          <p className="muted">{t("raci.empty_hint")}</p>
        </div>
      ) : (
        <div className="raci-scroll">
        <TableWrap wide>
          <table className="raci-table">
            <caption className="visually-hidden">
              {t("raci.caption", { n: rows.length })}
            </caption>
            <thead>
              <tr>
                <th scope="col">{t("raci.th_id")}</th>
                {ROLE_CODES.map((code) => (
                  <th
                    key={code}
                    scope="col"
                    className={`raci-role-h${focus === code ? " focus" : ""}`}
                  >
                    <button type="button" className="th-btn" onClick={() => setFocus(code)}>
                      {code}
                    </button>
                  </th>
                ))}
                <th scope="col">{t("raci.th_task")}</th>
                <th scope="col">{t("raci.th_artefact")}</th>
              </tr>
            </thead>
            <tbody>
              {grouped.map((g) => (
                <Fragment key={g.id}>
                  <tr className="raci-phase">
                    <th scope="colgroup" colSpan={9}>
                      {g.id}. {t(`raci.phase.${g.id}`)}
                      <span className="muted"> · {g.tasks.length}</span>
                    </th>
                  </tr>
                  {g.tasks.map((task) => (
                    <tr key={task.id}>
                      <td className="mono raci-id">{task.id}</td>
                      {ROLE_CODES.map((code) => {
                        const letter = lettersOf(task, code);
                        const dim = Boolean(focus && focus !== code);
                        return (
                          <td key={code} className={focus === code ? "col-focus" : undefined}>
                            <span
                              className={cellClass(letter, dim)}
                              title={
                                letter
                                  ? t(`raci.letter_${letterKey(letter)}`)
                                  : t("raci.unassigned")
                              }
                            >
                              {letter || "·"}
                            </span>
                          </td>
                        );
                      })}
                      <td>{t(`raci.task.${task.id}`)}</td>
                      <td className="raci-art">
                        <code>{task.artefact}</code>
                      </td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </TableWrap>
        </div>
      )}
      <p className="chart-note">{t("raci.showing", { n: rows.length })}</p>

      <section className="panel" style={{ marginTop: 28 }}>
        <header className="panel-head">
          <div>
            <h2>{t("raci.workload_h")}</h2>
            <p className="panel-note">{t("raci.workload_p")}</p>
          </div>
        </header>
        <div className="workload">
          {WORKLOAD.map((w) => (
            <div key={w.code} className="workload-row">
              <div className="workload-meta">
                <span className="role-code">{w.code}</span>
                <span>{t(`raci.role.${w.code}.short`)}</span>
                <span className="muted mono">{w.total}</span>
              </div>
              <div className="workload-bar" aria-hidden="true">
                <span className="seg r" style={{ width: `${(w.r / maxLoad) * 100}%` }} />
                <span className="seg a" style={{ width: `${(w.a / maxLoad) * 100}%` }} />
                <span className="seg c" style={{ width: `${(w.c / maxLoad) * 100}%` }} />
                <span className="seg i" style={{ width: `${(w.i / maxLoad) * 100}%` }} />
              </div>
              <div className="workload-counts muted">
                R {w.r} · A {w.a} · C {w.c} · I {w.i}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <header className="panel-head">
          <div>
            <h2>{t("raci.bottlenecks_h")}</h2>
            <p className="panel-note">{t("raci.bottlenecks_p")}</p>
          </div>
        </header>
        <ol className="risk-list">
          <li>
            <Trans i18nKey="raci.bn1" components={{ strong: <strong /> }} />
          </li>
          <li>
            <Trans i18nKey="raci.bn2" components={{ strong: <strong />, code: <code /> }} />
          </li>
          <li>
            <Trans i18nKey="raci.bn3" components={{ strong: <strong />, code: <code /> }} />
          </li>
          <li>
            <Trans i18nKey="raci.bn4" components={{ strong: <strong /> }} />
          </li>
          <li>
            <Trans i18nKey="raci.bn5" components={{ strong: <strong /> }} />
          </li>
        </ol>
      </section>

      <p className="lede" style={{ marginBottom: 0 }}>
        <Trans
          i18nKey="raci.foot"
          components={{ methodlink: <Link to="/method" /> }}
        />
      </p>
    </div>
  );
}
