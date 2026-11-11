import { useAction } from "./components/AsyncAction";
import { useEffect, useState, useId, cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { tr } from "./i18n/backendMap";
import type { RiskLevel } from "./api";
import type { RequestState } from "./hooks";

/** Shared page title block so every route opens with the same rhythm. */
export function PageHead({
  kicker,
  title,
  lede,
  kickerPlain,
  actions,
}: {
  kicker: string;
  title: string;
  lede?: ReactNode;
  /** Keep the kicker in source case (procedure IDs). */
  kickerPlain?: boolean;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className={kickerPlain ? "kicker kicker-plain mono" : "kicker"}>{kicker}</div>
      <h1>{title}</h1>
      {lede && <p className="lede">{lede}</p>}
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

/** Shown while a request is in flight, so the page never renders a bare "Loading…". */
export function Skeleton({ rows = 3, height = 16 }: { rows?: number; height?: number }) {
  return (
    <div className="skeleton" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="skeleton-row"
          style={{ height, width: `${100 - i * 9}%` }}
        />
      ))}
    </div>
  );
}

/**
 * Announced to screen readers while loading, and removed as soon as the content
 * lands, so a filter change is perceptible without sight.
 */
export function Loading({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label ?? t("common.loading")}
    </div>
  );
}

export function ErrorNote({
  error,
  onRetry,
}: {
  error: string;
  onRetry?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="error" role="alert">
      <div>
        <strong>{t("common.could_not_load")}</strong>
        <div className="error-detail">{error}</div>
      </div>
      {onRetry && (
        <button className="ghost" onClick={onRetry}>
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

/** A filter that matches nothing must say so, not render a header-only table. */
export function Empty({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      {hint && <p className="muted">{hint}</p>}
      {action}
    </div>
  );
}

/**
 * The five analytics requests share one state machine so every panel answers the
 * same questions: loading (with a live-region announcement), success, empty and
 * error — and a result loaded for *other* parameters is only ever shown behind
 * an explicit "updating" marker that names the parameters it belongs to.
 */
export function RequestPanel<T>({
  state,
  describe = (key: string) => key,
  isEmpty,
  pending,
  loadingLabel,
  emptyTitle,
  emptyHint,
  emptyAction,
  children,
}: {
  state: RequestState<T>;
  /** Human label for a parameter key (used in the stale marker and announcements). */
  describe?: (key: string) => string;
  isEmpty?: (data: T) => boolean;
  /** Node while loading with nothing on hand; defaults to the shared spinner. */
  pending?: ReactNode;
  loadingLabel?: string;
  emptyTitle?: string;
  emptyHint?: string;
  emptyAction?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  const { t } = useTranslation();
  // One persistent polite live region: its text changes as the request moves
  // through loading → updating → done, so a screen reader hears each phase.
  const announcement = state.error
    ? ""
    : state.loading && state.data === null
      ? t("common.results_loading", { params: describe(state.key) })
      : state.stale
        ? t("common.results_updating", {
            shown: describe(state.dataKey ?? ""),
            waiting: describe(state.key),
          })
        : state.data !== null
          ? t("common.results_ready", { params: describe(state.dataKey ?? state.key) })
          : "";

  if (state.error !== null) {
    return (
      <>
        <div role="status" aria-live="polite" className="visually-hidden">{announcement}</div>
        <ErrorNote error={state.error} onRetry={state.reload} />
      </>
    );
  }
  if (state.data === null) {
    return (
      <>
        <div role="status" aria-live="polite" className="visually-hidden">{announcement}</div>
        {state.loading ? pending ?? <Loading label={loadingLabel} /> : null}
      </>
    );
  }
  const empty = isEmpty?.(state.data) ?? false;
  return (
    <>
      <div role="status" aria-live="polite" className="visually-hidden">{announcement}</div>
      {state.stale && (
        <div className="stale-note" role="status">
          <span className="spinner" aria-hidden="true" />
          {t("common.stale_marker", {
            shown: describe(state.dataKey ?? ""),
            waiting: describe(state.key),
          })}
        </div>
      )}
      {empty ? <Empty title={emptyTitle ?? t("common.none")} hint={emptyHint} action={emptyAction} /> : children(state.data)}
    </>
  );
}

/**
 * The band is derived from how many detectors agreed, so the dot and the label
 * always carry the same meaning as the /api/stats band counts. An unscored
 * record shows "not scored" and hides the detector tally, because a count of
 * 0/4 detectors would read as "all four examined it and disagreed".
 */
export function BandBadge({
  level,
  nModels,
}: {
  level: RiskLevel | null | undefined;
  nModels?: number | null;
}) {
  const { t } = useTranslation();
  const key: RiskLevel = (level ?? "unscored") as RiskLevel;
  return (
    <span className="badge-wrap">
      <span className={`badge ${key}`}>
        <span className={`dot ${key}`} aria-hidden="true" />
        {t(`risk.${key}`)}
      </span>
      {key !== "unscored" && nModels !== null && nModels !== undefined && (
        <span className="muted models">{t("risk.detectors", { count: nModels })}</span>
      )}
    </span>
  );
}

/** Wraps wide tables so they scroll instead of stretching the whole page. */
export function TableWrap({
  children,
  wide,
}: {
  children: ReactNode;
  /** Ask for a larger minimum width, for tables with five or more columns. */
  wide?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      className={wide ? "table-wrap wide" : "table-wrap"}
      tabIndex={0}
      role="region"
      aria-label={t("common.table_scrollable")}
    >
      {children}
    </div>
  );
}

export function Stat({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: RiskLevel;
}) {
  return (
    <div className={`card${tone ? ` tone-${tone}` : ""}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {note && <div className="note">{note}</div>}
    </div>
  );
}

/* ==========================================================================
   Workspace primitives
   ========================================================================== */

export function Panel({
  title,
  note,
  actions,
  children,
}: {
  title: string;
  note?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel-head">
        <div>
          <h2>{title}</h2>
          {note && <p className="panel-note">{note}</p>}
        </div>
        {actions && <div className="panel-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  panelId,
}: {
  tabs: { key: T; label: string; count?: number }[];
  active: T;
  onChange: (key: T) => void;
  panelId?: string;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          id={panelId ? `${panelId}-${t.key}` : undefined}
          aria-controls={panelId}
          aria-selected={t.key === active}
          tabIndex={t.key === active ? 0 : -1}
          onKeyDown={(event) => {
            const index = tabs.findIndex((tab) => tab.key === t.key);
            const next = event.key === "ArrowRight" ? (index + 1) % tabs.length
              : event.key === "ArrowLeft" ? (index - 1 + tabs.length) % tabs.length
              : event.key === "Home" ? 0
              : event.key === "End" ? tabs.length - 1 : -1;
            if (next < 0) return;
            event.preventDefault();
            onChange(tabs[next].key);
            const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
            buttons?.[next].focus();
          }}
          className={`tab${t.key === active ? " active" : ""}`}
          onClick={() => onChange(t.key)}
        >
          {t.label}
          {t.count !== undefined && <span className="tab-count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Field({
  label,
  children,
  hint,
  grow,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
  grow?: boolean;
}) {
  const labelId = useId();
  return (
    <label className={`field${grow ? " grow" : ""}`}>
      <span id={labelId}>{label}</span>
      {isValidElement(children) ? cloneElement(children as ReactElement<{"aria-labelledby"?: string}>, {"aria-labelledby": labelId}) : children}
      {hint && <em className="field-hint">{hint}</em>}
    </label>
  );
}

/** Inline confirmation for destructive actions, so a stray click cannot delete. */
export function ConfirmButton({
  onConfirm,
  children,
  confirmLabel,
  className = "ghost danger",
  disabled,
}: {
  onConfirm: () => void | Promise<void>;
  children: ReactNode;
  confirmLabel?: string;
  className?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [armed, setArmed] = useState(false);
  const action = useAction();
  useEffect(() => {
    if (!armed || action.pending || action.error) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed, action.pending, action.error]);
  if (armed) {
    return (
      <span className="confirm">
        <button type="button" className="danger" disabled={disabled || action.pending} aria-busy={action.pending} onClick={() => void action.run(async () => { await onConfirm(); setArmed(false); })}>
          {action.pending ? t("completion.pending") : confirmLabel ?? t("common.confirm_delete")}
        </button>
        {action.error && <span role="alert">{action.error}</span>}
        {action.pending && <span role="status" className="visually-hidden">{t("completion.pending")}</span>}
        <button type="button" className="ghost" disabled={action.pending} onClick={() => setArmed(false)}>
          {t("common.cancel")}
        </button>
      </span>
    );
  }
  return (
    <button type="button" className={className} onClick={() => setArmed(true)} disabled={disabled}>
      {children}
    </button>
  );
}

export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onDone, 3500);
    return () => clearTimeout(t);
  }, [message, onDone]);
  if (!message) return null;
  return (
    <div className="toast" role="status" aria-live="polite">
      {message}
    </div>
  );
}

export function Pill({ tone, children }: { tone: string; children: ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

const PRIORITY_TONE: Record<string, string> = {
  low: "muted",
  medium: "info",
  high: "warn",
  critical: "risk",
};

const STATUS_TONE: Record<string, string> = {
  open: "info",
  "in review": "warn",
  escalated: "risk",
  closed: "muted",
  dismissed: "muted",
};

/** Case/watchlist priority from the workspace API, localised via the map. */
export function PriorityPill({ value }: { value: string }) {
  return <Pill tone={PRIORITY_TONE[value] ?? "muted"}>{tr(value)}</Pill>;
}

/** Case status from the workspace API, localised via the map. */
export function StatusPill({ value }: { value: string }) {
  return <Pill tone={STATUS_TONE[value] ?? "muted"}>{tr(value)}</Pill>;
}

/** Compact key statistics row used above the distribution charts. */
export function MiniStats({
  items,
}: {
  items: { label: string; value: ReactNode; tone?: string }[];
}) {
  return (
    <div className="mini-stats">
      {items.map((i) => (
        <div key={i.label} className={`mini-stat${i.tone ? ` ${i.tone}` : ""}`}>
          <span className="mini-label">{i.label}</span>
          <span className="mini-value">{i.value}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Colour scale for a correlation cell: teal for negative, gold for positive.
 *
 * The ramp comes from semantic tokens (`--chart-teal` / `--chart-gold`) so the
 * same function works in both themes without post-hoc CSS overrides of
 * Recharts internals; ``color-mix`` keeps it a plain SVG/CSS colour string.
 */
export function corrColor(v: number | null, max = 1): string {
  if (v === null || Number.isNaN(v)) return "var(--surface-secondary)";
  const t = Math.min(Math.abs(v) / max, 1);
  const share = Math.round((0.1 + 0.3 * t) * 100);
  return v >= 0
    ? `color-mix(in srgb, var(--chart-gold) ${share}%, transparent)`
    : `color-mix(in srgb, var(--chart-teal) ${share}%, transparent)`;
}
