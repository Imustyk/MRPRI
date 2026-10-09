import { useEffect, useState, type ReactNode } from "react";
import type { RiskLevel } from "./api";

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
export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      {label}
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
  return (
    <div className="error" role="alert">
      <div>
        <strong>Could not load this view.</strong>
        <div className="error-detail">{error}</div>
      </div>
      {onRetry && (
        <button className="ghost" onClick={onRetry}>
          Retry
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

const LEVEL_TEXT: Record<RiskLevel, string> = {
  unscored: "not scored",
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};

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
  const key: RiskLevel = (level ?? "unscored") as RiskLevel;
  return (
    <span className="badge-wrap">
      <span className={`badge ${key}`}>
        <span className={`dot ${key}`} aria-hidden="true" />
        {LEVEL_TEXT[key]}
      </span>
      {key !== "unscored" && nModels !== null && nModels !== undefined && (
        <span className="muted models">{nModels}/4 detectors</span>
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
  return (
    <div
      className={wide ? "table-wrap wide" : "table-wrap"}
      tabIndex={0}
      role="region"
      aria-label="Data table, scrollable"
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
}: {
  tabs: { key: T; label: string; count?: number }[];
  active: T;
  onChange: (key: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={t.key === active}
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
  return (
    <label className={`field${grow ? " grow" : ""}`}>
      <span>{label}</span>
      {children}
      {hint && <em className="field-hint">{hint}</em>}
    </label>
  );
}

/** Inline confirmation for destructive actions, so a stray click cannot delete. */
export function ConfirmButton({
  onConfirm,
  children,
  confirmLabel = "Confirm delete",
  className = "ghost danger",
  disabled,
}: {
  onConfirm: () => void;
  children: ReactNode;
  confirmLabel?: string;
  className?: string;
  disabled?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 4000);
    return () => clearTimeout(t);
  }, [armed]);
  if (armed) {
    return (
      <span className="confirm">
        <button className="danger" onClick={onConfirm}>
          {confirmLabel}
        </button>
        <button className="ghost" onClick={() => setArmed(false)}>
          Cancel
        </button>
      </span>
    );
  }
  return (
    <button className={className} onClick={() => setArmed(true)} disabled={disabled}>
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

export function PriorityPill({ value }: { value: string }) {
  return <Pill tone={PRIORITY_TONE[value] ?? "muted"}>{value}</Pill>;
}

export function StatusPill({ value }: { value: string }) {
  return <Pill tone={STATUS_TONE[value] ?? "muted"}>{value}</Pill>;
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

/** Colour scale for a correlation cell: teal for negative, gold for positive. */
export function corrColor(v: number | null, max = 1): string {
  if (v === null || Number.isNaN(v)) return "#f1f2f4";
  const t = Math.min(Math.abs(v) / max, 1);
  const alpha = 0.1 + 0.62 * t;
  return v >= 0 ? `rgba(184,137,42,${alpha.toFixed(3)})` : `rgba(42,127,143,${alpha.toFixed(3)})`;
}
