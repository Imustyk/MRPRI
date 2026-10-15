import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  getGraph,
  int,
  mdl,
  num,
  pctile,
  type GraphData,
  type GraphLink,
  type GraphNode,
} from "../api";
import { Empty, ErrorNote, Field, PageHead, Skeleton, TableWrap } from "../ui";
import { EDGE_FILL, edgeBand, isUnscored } from "./network/band";
import { layoutGraph } from "./network/layout";

/* ==========================================================================
   Constants
   ========================================================================== */

/** Two bounded slices per load: strongest pairs (by awards) + most anomalous. */
const SLICE_LIMIT = 1500;
/** Matrix axes default: the top parties by number of connections. */
const TOP_OPTIONS = [25, 50, 75, 100];
const TOP_DEFAULT = 50;
/** The drill-down draws at most this many partners around one party. */
const DRILL_MAX = 30;
/** The table shows the head of the ranking; the CSV export carries the rest. */
const TABLE_CAP = 100;
/** Label gutters around the cell grid. */
const AXIS_W = 190;
const AXIS_H = 124;
/** Cell size bounds: 8px is the smallest pitch where an 8px axis label fits. */
const CELL_MIN = 8;
const CELL_MAX = 18;

const NAVY = "#1e3a5f";
const GOLD = "#b8892a";

const pairKey = (l: GraphLink) => `${l.source}||${l.target}`;
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

type Cells = Map<string, { link: GraphLink; ri: number; ci: number }>;

/* ==========================================================================
   Data: two bounded slices merged into one view
   ========================================================================== */

/**
 * The endpoint is bounded (top N pairs, one ranking at a time), so a single
 * call can hide exactly what this page is about: ranked by awards it drops the
 * high-percentile pairs with few awards, ranked by risk it drops the heavy
 * repeat relationships. Both slices are fetched and unioned client-side.
 *
 * Nothing is recomputed here: `weight`, `value` and `max_risk` arrive from the
 * server, only slice-relative bookkeeping (`degree`, the shown counters) is
 * recomputed so the union cannot report either slice's numbers as its own.
 */
function mergeSlices(
  a: GraphData,
  b: GraphData,
): { links: GraphLink[]; nodes: Map<string, GraphNode>; stats: GraphData["stats"] } {
  const nodes = new Map<string, GraphNode>();
  for (const n of a.nodes) nodes.set(n.id, n);
  for (const n of b.nodes) nodes.set(n.id, n);
  const isBuyer = (id: string) => nodes.get(id)?.kind === "buyer";

  const byPair = new Map<string, GraphLink>();
  const add = (l: GraphLink) => {
    // Normalise direction: source is always the authority, so rows, columns and
    // drill-down never depend on how a slice happened to rank the pair.
    const norm =
      isBuyer(l.source) || !isBuyer(l.target) ? l : { ...l, source: l.target, target: l.source };
    const key = pairKey(norm);
    if (!byPair.has(key)) byPair.set(key, norm);
  };
  a.links.forEach(add);
  b.links.forEach(add);

  const links = [...byPair.values()];
  const degree = new Map<string, number>();
  for (const l of links) {
    degree.set(l.source, (degree.get(l.source) ?? 0) + 1);
    degree.set(l.target, (degree.get(l.target) ?? 0) + 1);
  }
  const merged = new Map<string, GraphNode>();
  for (const [id, n] of nodes) merged.set(id, { ...n, degree: degree.get(id) ?? 0 });

  const stats: GraphData["stats"] = {
    ...a.stats,
    nodes_shown: merged.size,
    pairs_shown: links.length,
    awards_shown: links.reduce((s, l) => s + l.weight, 0),
    value_shown: links.reduce((s, l) => s + l.value, 0),
    truncated: links.length < a.stats.pairs_qualifying,
  };
  return { links, nodes: merged, stats };
}

/* ==========================================================================
   Shared tooltip
   ========================================================================== */

function Tip({
  x,
  y,
  title,
  sub,
  rows,
}: {
  x: number;
  y: number;
  title: string;
  sub?: string;
  rows: [string, string][];
}) {
  // Flip before the right/bottom edge so a cell near the border stays readable.
  const left = Math.max(8, Math.min(x + 14, window.innerWidth - 260));
  const top = Math.max(8, Math.min(y + 16, window.innerHeight - 160));
  return (
    <div className="vz-tip" style={{ left, top }} aria-hidden="true">
      <div className="vz-tip-title">{title}</div>
      {sub && <div className="vz-tip-sub">{sub}</div>}
      {rows.map(([k, v]) => (
        <div className="vz-tip-row" key={k}>
          <span>{k}</span>
          <b>{v}</b>
        </div>
      ))}
    </div>
  );
}

/* ==========================================================================
   Matrix: authorities down, suppliers across
   ========================================================================== */

function Matrix({
  rows,
  cols,
  cells,
  nodes,
  selected,
  onSelect,
  onDrill,
}: {
  rows: string[];
  cols: string[];
  cells: Cells;
  nodes: Map<string, GraphNode>;
  selected: GraphLink | null;
  onSelect: (l: GraphLink) => void;
  onDrill: (id: string) => void;
}) {
  const { t } = useTranslation();
  const hostRef = useRef<HTMLDivElement>(null);
  const [hostW, setHostW] = useState(720);
  const [hover, setHover] = useState<{ link: GraphLink; x: number; y: number } | null>(null);

  // The grid sizes itself to the card so 50 columns stay square and legible;
  // a wider slice (75/100) scrolls instead of shrinking cells below 7px.
  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    setHostW(el.clientWidth);
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setHostW(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const nameOf = useCallback((id: string) => nodes.get(id)?.name ?? id, [nodes]);
  const cell = Math.max(
    CELL_MIN,
    Math.min(CELL_MAX, Math.floor((hostW - AXIS_W - 8) / Math.max(cols.length, 1))),
  );
  const gridW = cols.length * cell;
  const gridH = rows.length * cell;

  const selRi = selected ? rows.indexOf(selected.source) : -1;
  const selCi = selected ? cols.indexOf(selected.target) : -1;
  const selKey = selected ? pairKey(selected) : null;

  // Cells and labels are memoised on data, not on hover, so pointing at a cell
  // re-renders only the tooltip: 10k reconciliations stay off the hover path.
  const cellEls = useMemo(() => {
    const out: ReactNode[] = [];
    cells.forEach((c, key) => {
      const band = edgeBand(c.link.max_risk);
      const unscored = isUnscored(band);
      const x = AXIS_W + c.ci * cell + 1;
      const y = AXIS_H + c.ri * cell + 1;
      const size = Math.max(3, cell - 2);
      // Fill is the band colour, and nothing crowds it out: at an 8px pitch a
      // second mark inside the cell would swallow the fill it is supposed to
      // complement. The award count rides on the tooltip, the aria-label and
      // the table instead, and "never scored" keeps its dashed outline.
      out.push(
        <rect
          key={key}
          className={`net-cell${selKey === key ? " net-cell-sel" : ""}`}
          x={x}
          y={y}
          width={size}
          height={size}
          rx={2}
          fill={EDGE_FILL[band]}
          stroke={unscored ? "#8b95a1" : "#d7dde4"}
          strokeDasharray={unscored ? "2 2" : undefined}
          onMouseEnter={(e) => setHover({ link: c.link, x: e.clientX, y: e.clientY })}
          onMouseLeave={() => setHover(null)}
          onClick={() => onSelect(c.link)}
          role="img"
          aria-label={t("network.cell_label", {
            a: nameOf(c.link.source),
            b: nameOf(c.link.target),
            w: num(c.link.weight),
            p: pctile(c.link.max_risk),
            v: mdl(c.link.value),
          })}
        />,
      );
    });
    return out;
  }, [cells, cell, selKey, nodes, t, onSelect]);

  const frameEls = useMemo(() => {
    const nameOfLocal = (id: string) => nodes.get(id)?.name ?? id;
    // Label typography follows the cell pitch: at the default 8px pitch the
    // labels drop to 8px so adjacent rows/columns never overlap, and they grow
    // with the cells on wider cards. Truncation is measured off the same font.
    const font = Math.max(8, Math.min(11, cell));
    const rowChars = Math.max(6, Math.floor((AXIS_W - 16) / (font * 0.56)));
    const colChars = Math.max(6, Math.floor((AXIS_H - 12) / (font * 0.6)));
    // Axis labels are the drill-down entry points, so they are real buttons:
    // focusable, named, and operable with Enter/Space.
    const key = (id: string) => (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onDrill(id);
      }
    };

    const rowEls = rows.map((id, ri) => {
      const y = AXIS_H + ri * cell + cell / 2 + 4;
      const sel = selected?.source === id;
      return (
        <text
          key={`r-${id}`}
          x={AXIS_W - 10}
          y={y}
          textAnchor="end"
          fontSize={font}
          fontWeight={sel ? 600 : 400}
          role="button"
          tabIndex={0}
          className="net-axis"
          aria-label={t("network.drill_open", { name: nameOfLocal(id) })}
          onClick={() => onDrill(id)}
          onKeyDown={key(id)}
        >
          {clip(nameOfLocal(id), rowChars)}
          <title>{nameOfLocal(id)}</title>
        </text>
      );
    });

    const colEls = cols.map((id, ci) => {
      const x = AXIS_W + ci * cell + cell / 2;
      const y = AXIS_H - 8;
      const sel = selected?.target === id;
      return (
        <text
          key={`c-${id}`}
          x={x}
          y={y}
          fontSize={font}
          fontWeight={sel ? 600 : 400}
          textAnchor="start"
          transform={`rotate(-90 ${x} ${y})`}
          role="button"
          tabIndex={0}
          className="net-axis"
          aria-label={t("network.drill_open", { name: nameOfLocal(id) })}
          onClick={() => onDrill(id)}
          onKeyDown={key(id)}
        >
          {clip(nameOfLocal(id), colChars)}
          <title>{nameOfLocal(id)}</title>
        </text>
      );
    });

    return (
      <>
        <rect
          x={AXIS_W}
          y={AXIS_H}
          width={gridW}
          height={gridH}
          fill="#fcfcfd"
          stroke="#eef0f3"
        />
        {selRi >= 0 && (
          <rect
            x={AXIS_W}
            y={AXIS_H + selRi * cell}
            width={gridW}
            height={cell}
            fill="#f8f1e3"
          />
        )}
        {selCi >= 0 && (
          <rect
            x={AXIS_W + selCi * cell}
            y={AXIS_H}
            width={cell}
            height={gridH}
            fill="#f8f1e3"
          />
        )}
        {/* A faint lattice: with a 50-row grid the eye needs a rail to follow a
            cell back to its row label and a column label down to its cell. */}
        {Array.from({ length: rows.length + 1 }, (_, i) => (
          <line
            key={`h-${i}`}
            x1={AXIS_W}
            x2={AXIS_W + gridW}
            y1={AXIS_H + i * cell}
            y2={AXIS_H + i * cell}
            stroke="#f0f2f5"
          />
        ))}
        {Array.from({ length: cols.length + 1 }, (_, i) => (
          <line
            key={`v-${i}`}
            x1={AXIS_W + i * cell}
            x2={AXIS_W + i * cell}
            y1={AXIS_H}
            y2={AXIS_H + gridH}
            stroke="#f0f2f5"
          />
        ))}
        {rowEls}
        {colEls}
      </>
    );
  }, [rows, cols, cell, gridW, gridH, selRi, selCi, selected, nodes, t, onDrill]);

  return (
    <div className="net-scroll" ref={hostRef}>
      <svg
        className="net-svg"
        width={AXIS_W + gridW + 6}
        height={AXIS_H + gridH + 6}
        role="group"
        aria-label={t("network.matrix_label", {
          rows: rows.length,
          cols: cols.length,
          n: cells.size,
        })}
      >
        {frameEls}
        {cellEls}
      </svg>
      {hover && (
        <Tip
          x={hover.x}
          y={hover.y}
          title={nameOf(hover.link.source)}
          sub={nameOf(hover.link.target)}
          rows={[
            [t("network.th_awards"), num(hover.link.weight)],
            [t("network.th_max"), pctile(hover.link.max_risk)],
            [t("network.th_value"), mdl(hover.link.value)],
          ]}
        />
      )}
    </div>
  );
}

/* ==========================================================================
   Ranked pairs: sortable, exportable, and wired back to the matrix
   ========================================================================== */

type SortKey = "buyer" | "supplier" | "awards" | "pct";
type SortState = { key: SortKey; dir: "asc" | "desc" };

/** Percentile first (nulls always last), awards as the tie-breaker. */
function rankPairs(pairs: GraphLink[], sort: SortState, nameOf: (id: string) => string) {
  const dir = sort.dir === "asc" ? 1 : -1;
  return [...pairs].sort((a, b) => {
    let d = 0;
    switch (sort.key) {
      case "buyer":
        d = nameOf(a.source).localeCompare(nameOf(b.source));
        break;
      case "supplier":
        d = nameOf(a.target).localeCompare(nameOf(b.target));
        break;
      case "awards":
        d = a.weight - b.weight;
        break;
      case "pct": {
        // "Never scored" is not a low percentile: unscored pairs stay last in
        // both directions instead of sorting in with the 0s.
        if (a.max_risk === null && b.max_risk !== null) return 1;
        if (b.max_risk === null && a.max_risk !== null) return -1;
        if (a.max_risk !== null && b.max_risk !== null) d = a.max_risk - b.max_risk;
        break;
      }
    }
    if (d !== 0) return d * dir;
    if (a.weight !== b.weight) return b.weight - a.weight;
    return nameOf(a.source).localeCompare(nameOf(b.source));
  });
}

function PairTable({
  pairs,
  nameOf,
  selected,
  onSelect,
  onClear,
}: {
  pairs: GraphLink[];
  nameOf: (id: string) => string;
  selected: string | null;
  onSelect: (l: GraphLink) => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const [sort, setSort] = useState<SortState>({ key: "pct", dir: "desc" });
  const sorted = useMemo(() => rankPairs(pairs, sort, nameOf), [pairs, sort, nameOf]);
  const shown = sorted.slice(0, TABLE_CAP);

  const toggle = (key: SortKey) =>
    setSort((s) =>
      s.key === key
        ? { key, dir: s.dir === "desc" ? "asc" : "desc" }
        : { key, dir: key === "buyer" || key === "supplier" ? "asc" : "desc" },
    );

  const exportCsv = () => {
    const header = ["authority", "supplier", "awards", "total_value_mdl", "max_anomaly_percentile"];
    const rows = sorted.map((p) => [
      nameOf(p.source),
      nameOf(p.target),
      p.weight,
      p.value,
      p.max_risk ?? "",
    ]);
    const csv =
      "\uFEFF" +
      [header, ...rows]
        .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","))
        .join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "buyer-winner-pairs.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const columns: { key: SortKey; label: string }[] = [
    { key: "buyer", label: t("network.th_authority") },
    { key: "supplier", label: t("network.th_supplier") },
    { key: "awards", label: t("network.th_awards") },
    // Value stays out of the table on purpose: it is the widest column and
    // would push the ranking into a horizontal scroll inside a narrow card.
    // It is carried by the tooltip, the CSV export and the drill-down list.
    { key: "pct", label: t("network.th_max") },
  ];

  return (
    <>
      <div className="net-card-head">
        <h2>{t("network.table_h")}</h2>
        <button
          type="button"
          className="ghost small"
          onClick={exportCsv}
          disabled={sorted.length === 0}
        >
          {t("network.btn_csv", { n: int(sorted.length) })}
        </button>
      </div>

      <TableWrap>
        <table className="sortable">
          <thead>
            <tr>
              {columns.map((c) => (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={
                    sort.key === c.key
                      ? sort.dir === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button type="button" onClick={() => toggle(c.key)}>
                    {c.label}
                    <span aria-hidden="true">
                      {sort.key === c.key ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((p) => {
              const key = pairKey(p);
              return (
                <tr
                  key={key}
                  className="clickable"
                  tabIndex={0}
                  aria-current={selected === key ? "true" : undefined}
                  onClick={() => onSelect(p)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(p);
                    }
                  }}
                >
                  <td>
                    <span className="clamp3" title={nameOf(p.source)}>
                      {nameOf(p.source)}
                    </span>
                  </td>
                  <td>
                    <span className="clamp3" title={nameOf(p.target)}>
                      {nameOf(p.target)}
                    </span>
                  </td>
                  <td className="mono">{num(p.weight)}</td>
                  <td className="mono">{pctile(p.max_risk)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableWrap>

      <p className="muted net-note">
        {t("network.table_note", { shown: int(shown.length), total: int(sorted.length) })}
        {selected && (
          <>
            {" "}
            {t("network.sel_note")}{" "}
            <button type="button" className="link" onClick={onClear}>
              {t("network.sel_clear")}
            </button>
          </>
        )}
      </p>
    </>
  );
}

/* ==========================================================================
   Drill-down: one party and its strongest partners, force-laid on canvas
   ========================================================================== */

function DrillCanvas({
  centerId,
  nodes,
  links,
  onDrill,
}: {
  centerId: string;
  nodes: GraphNode[];
  links: GraphLink[];
  onDrill: (id: string) => void;
}) {
  const { t } = useTranslation();
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [w, setW] = useState(560);
  const [hover, setHover] = useState<string | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null);
  const H = 340;

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    setW(Math.max(260, Math.min(900, el.clientWidth)));
    const ro = new ResizeObserver((entries) => {
      const cw = entries[0]?.contentRect.width;
      if (cw) setW(Math.max(260, Math.min(900, cw)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Deterministic Fruchterman-Reingold from the existing toolkit: the same
  // slice always draws the same picture, and 31 nodes settle in milliseconds.
  const placed = useMemo(() => layoutGraph(nodes, links, w, H), [nodes, links, w]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(H * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${H}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, H);

    for (const l of links) {
      const a = placed.get(l.source);
      const b = placed.get(l.target);
      if (!a || !b) continue;
      const band = edgeBand(l.max_risk);
      ctx.strokeStyle = EDGE_FILL[band];
      ctx.lineWidth = 1 + Math.min(4, l.weight * 0.4);
      ctx.setLineDash(isUnscored(band) ? [4, 3] : []);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (const n of nodes) {
      const p = placed.get(n.id);
      if (!p) continue;
      const isCenter = n.id === centerId;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = n.kind === "buyer" ? NAVY : GOLD;
      ctx.fill();
      ctx.lineWidth = hover === n.id ? 3 : 1.5;
      ctx.strokeStyle = hover === n.id ? "#1b2430" : "#ffffff";
      ctx.stroke();

      const label = clip(n.name, isCenter ? 26 : 14);
      ctx.font = `${isCenter ? "600 " : ""}10px "IBM Plex Sans", system-ui, sans-serif`;
      const ly = p.y + p.r + 4;
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(255,255,255,0.92)";
      ctx.strokeText(label, p.x, ly);
      ctx.fillStyle = "#1b2430";
      ctx.fillText(label, p.x, ly);
    }
  }, [placed, hover, nodes, links, centerId, w, H]);

  const nodeAt = (x: number, y: number): string | null => {
    for (const n of nodes) {
      const p = placed.get(n.id);
      if (!p) continue;
      if (Math.hypot(p.x - x, p.y - y) <= p.r + 3) return n.id;
    }
    return null;
  };

  const nameOf = (id: string) => nodes.find((n) => n.id === id)?.name ?? id;
  const hoveredNode = hover ? nodes.find((n) => n.id === hover) : null;

  return (
    <div className="net-drill-canvas" ref={hostRef}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={t("network.drill_canvas", {
          name: nameOf(centerId),
          n: links.length,
        })}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const id = nodeAt(e.clientX - rect.left, e.clientY - rect.top);
          if (id !== hover) {
            setHover(id);
            setTip(id ? { x: e.clientX, y: e.clientY } : null);
            e.currentTarget.style.cursor = id && id !== centerId ? "pointer" : "default";
          }
        }}
        onMouseLeave={() => {
          setHover(null);
          setTip(null);
        }}
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const id = nodeAt(e.clientX - rect.left, e.clientY - rect.top);
          if (id && id !== centerId) onDrill(id);
        }}
      />
      {tip && hoveredNode && (
        <Tip
          x={tip.x}
          y={tip.y}
          title={hoveredNode.name}
          sub={
            hoveredNode.kind === "buyer" ? t("network.kind_buyer") : t("network.kind_supplier")
          }
          rows={[
            [t("network.th_awards"), num(hoveredNode.awards)],
            [t("network.th_max"), pctile(hoveredNode.max_risk)],
            [t("network.th_value"), mdl(hoveredNode.value)],
          ]}
        />
      )}
    </div>
  );
}

/* ==========================================================================
   Page
   ========================================================================== */

export default function Network() {
  const { t } = useTranslation();
  const [slice, setSlice] = useState<{
    links: GraphLink[];
    nodes: Map<string, GraphNode>;
    stats: GraphData["stats"];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // View state (filters do not touch the API or the percentile maths).
  const [minAwards, setMinAwards] = useState(2);
  const [minPct, setMinPct] = useState(0);
  const [search, setSearch] = useState("");
  const [topN, setTopN] = useState(TOP_DEFAULT);
  const [selKey, setSelKey] = useState<string | null>(null);
  // #drill=<party id> opens that party's local network on load, so a drill-down
  // view is shareable (and the state survives a reload).
  const [drill, setDrill] = useState<string | null>(() => {
    const hit = /#drill=([^&]+)/.exec(window.location.hash);
    return hit ? decodeURIComponent(hit[1]) : null;
  });
  const matrixRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      getGraph({ limit: SLICE_LIMIT, sort: "awards" }),
      getGraph({ limit: SLICE_LIMIT, sort: "risk" }),
    ])
      .then(([byAwards, byRisk]) => {
        setSlice(mergeSlices(byAwards, byRisk));
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  }, []);

  useEffect(load, [load]);

  // Keep the address bar in step with the opened drill-down (replaceState: a
  // drill-down click is navigation *within* the view, not a history entry).
  useEffect(() => {
    const base = `${window.location.pathname}${window.location.search}`;
    window.history.replaceState(
      null,
      "",
      drill ? `${base}#drill=${encodeURIComponent(drill)}` : base,
    );
  }, [drill]);

  const nameOf = useCallback((id: string) => slice?.nodes.get(id)?.name ?? id, [slice]);

  const filtered = useMemo(() => {
    if (!slice) return [];
    const q = search.trim().toLowerCase();
    return slice.links.filter((l) => {
      if (l.weight < minAwards) return false;
      // 0 means "keep everything, including pairs no model ever scored";
      // any positive threshold cannot be met by an unscored pair.
      if (minPct > 0 && (l.max_risk === null || l.max_risk < minPct)) return false;
      if (q) {
        const hit =
          nameOf(l.source).toLowerCase().includes(q) ||
          nameOf(l.target).toLowerCase().includes(q);
        if (!hit) return false;
      }
      return true;
    });
  }, [slice, minAwards, minPct, search, nameOf]);

  /** Axes (top-N by connections) plus every cell that falls inside them. */
  const grid = useMemo(() => {
    const bDeg = new Map<string, number>();
    const sDeg = new Map<string, number>();
    const bump = (m: Map<string, number>, k: string) => m.set(k, (m.get(k) ?? 0) + 1);
    for (const l of filtered) {
      bump(bDeg, l.source);
      bump(sDeg, l.target);
    }
    const rank = (m: Map<string, number>) =>
      [...m.entries()]
        .map(([id, deg]) => ({ id, deg, name: nameOf(id) }))
        .sort((a, b) => b.deg - a.deg || a.name.localeCompare(b.name))
        .slice(0, topN)
        .map((r) => r.id);

    let rows = rank(bDeg);
    let cols = rank(sDeg);

    // A pair selected from the table must have a cell to outline, even when it
    // sits outside the top-N: its axes are appended so the outline can exist.
    const selected = selKey ? filtered.find((l) => pairKey(l) === selKey) : undefined;
    if (selected) {
      if (!rows.includes(selected.source)) rows = [...rows, selected.source];
      if (!cols.includes(selected.target)) cols = [...cols, selected.target];
    }

    const rowIdx = new Map(rows.map((id, i) => [id, i]));
    const colIdx = new Map(cols.map((id, i) => [id, i]));
    const cells: Cells = new Map();
    for (const l of filtered) {
      const ri = rowIdx.get(l.source);
      const ci = colIdx.get(l.target);
      if (ri !== undefined && ci !== undefined) cells.set(pairKey(l), { link: l, ri, ci });
    }
    return { rows, cols, cells, selected: selected ?? null };
  }, [filtered, topN, selKey, nameOf]);

  const drillData = useMemo(() => {
    if (!slice || !drill) return null;
    const links = slice.links
      .filter((l) => l.source === drill || l.target === drill)
      .sort((a, b) => b.weight - a.weight || (b.max_risk ?? -1) - (a.max_risk ?? -1))
      .slice(0, DRILL_MAX);
    if (links.length === 0) return null;
    const ids = new Set<string>([drill]);
    const deg = new Map<string, number>();
    for (const l of links) {
      ids.add(l.source);
      ids.add(l.target);
      deg.set(l.source, (deg.get(l.source) ?? 0) + 1);
      deg.set(l.target, (deg.get(l.target) ?? 0) + 1);
    }
    const nodes = [...ids]
      .map((id) => slice.nodes.get(id))
      .filter((n): n is GraphNode => n !== undefined)
      .map((n) => ({ ...n, degree: deg.get(n.id) ?? 0 }));
    return { nodes, links, degree: deg.get(drill) ?? 0 };
  }, [slice, drill]);

  const selectPair = useCallback((l: GraphLink) => {
    setSelKey(pairKey(l));
    matrixRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, []);

  const resetFilters = () => {
    setMinAwards(2);
    setMinPct(0);
    setSearch("");
    setTopN(TOP_DEFAULT);
  };

  if (loading) {
    return (
      <div>
        <h1>{t("network.loading_title")}</h1>
        <Skeleton rows={8} height={28} />
      </div>
    );
  }

  if (error || !slice) {
    return (
      <div>
        <h1>{t("network.loading_title")}</h1>
        <ErrorNote error={error ?? t("network.no_graph")} onRetry={load} />
      </div>
    );
  }

  if (slice.links.length === 0) {
    return (
      <div>
        <PageHead kicker={t("network.kicker")} title={t("network.title")} />
        <Empty title={t("network.empty")} hint={t("network.empty_hint")} />
      </div>
    );
  }

  const coverage =
    slice.stats.pairs_shown < slice.stats.pairs_qualifying
      ? t("network.coverage", {
          shown: int(slice.stats.pairs_shown),
          qualifying: int(slice.stats.pairs_qualifying),
          slice: int(SLICE_LIMIT),
        })
      : t("network.coverage_all", { n: int(slice.stats.pairs_qualifying) });

  return (
    <div>
      <PageHead kicker={t("network.kicker")} title={t("network.title")} lede={t("network.lede")} />

      <ul className="legend">
        <li>
          <span className="swatch" style={{ background: NAVY }} /> {t("network.legend_authority")}
        </li>
        <li>
          <span className="swatch" style={{ background: GOLD }} /> {t("network.legend_supplier")}
        </li>
        <li>
          <span className="swatch box" style={{ background: EDGE_FILL.high }} />{" "}
          {t("network.legend_high")}
        </li>
        <li>
          <span className="swatch box" style={{ background: EDGE_FILL.mid }} />{" "}
          {t("network.legend_mid")}
        </li>
        <li>
          <span className="swatch box" style={{ background: EDGE_FILL.low }} />{" "}
          {t("network.legend_low")}
        </li>
        <li>
          <span className="swatch box dashed" /> {t("network.legend_unscored")}
        </li>
      </ul>

      <div className="toolbar net-filters">
        <Field label={t("network.f_min_awards")}>
          <input
            type="number"
            min={2}
            max={100}
            value={minAwards}
            onChange={(e) => setMinAwards(Math.max(2, Number(e.target.value) || 2))}
          />
        </Field>
        <Field label={t("network.f_min_percentile")} hint={t("network.f_min_percentile_hint")}>
          <input
            type="number"
            min={0}
            max={100}
            step={5}
            value={minPct}
            onChange={(e) =>
              setMinPct(Math.min(100, Math.max(0, Number(e.target.value) || 0)))
            }
          />
        </Field>
        <Field label={t("network.f_search")} grow>
          <input
            type="search"
            value={search}
            placeholder={t("network.ph_search")}
            onChange={(e) => setSearch(e.target.value)}
          />
        </Field>
        <Field label={t("network.f_top")}>
          <select value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
            {TOP_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {t("network.top_opt", { n })}
              </option>
            ))}
          </select>
        </Field>
        <button type="button" className="ghost" onClick={resetFilters}>
          {t("common.reset")}
        </button>
      </div>

      <p className="muted net-note">{coverage}</p>

      {filtered.length === 0 || grid.rows.length === 0 || grid.cols.length === 0 ? (
        <Empty title={t("network.filters_empty")} hint={t("network.filters_empty_hint")} />
      ) : (
        <div className="net-grid">
          <section className="card net-card" ref={matrixRef} aria-label={t("network.matrix_h")}>
            <div className="net-card-head">
              <h2>{t("network.matrix_h")}</h2>
            </div>
            <p className="muted net-note">{t("network.matrix_note")}</p>
            <Matrix
              rows={grid.rows}
              cols={grid.cols}
              cells={grid.cells}
              nodes={slice.nodes}
              selected={grid.selected}
              onSelect={selectPair}
              onDrill={(id) => setDrill(id)}
            />

            {drill && (
              <div className="net-drill">
                <div className="net-card-head">
                  <h3>
                    {t("network.drill_h")}: {nameOf(drill)}
                  </h3>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => setDrill(null)}
                  >
                    {t("common.close")}
                  </button>
                </div>
                {drillData ? (
                  <>
                    <p className="muted net-note">
                      {t("network.drill_note", {
                        name: nameOf(drill),
                        n: drillData.links.length,
                      })}
                    </p>
                    <DrillCanvas
                      centerId={drill}
                      nodes={drillData.nodes}
                      links={drillData.links}
                      onDrill={(id) => setDrill(id)}
                    />
                    <details className="net-drill-list">
                      <summary>{t("network.drill_list")}</summary>
                      <ul>
                        {drillData.links.map((l) => {
                          const other = l.source === drill ? l.target : l.source;
                          return (
                            <li key={pairKey(l)}>
                              {nameOf(other)} — {num(l.weight)} · {t("network.th_max")}{" "}
                              {pctile(l.max_risk)} · {mdl(l.value)}
                            </li>
                          );
                        })}
                      </ul>
                    </details>
                  </>
                ) : (
                  <p className="muted">{t("network.drill_empty")}</p>
                )}
              </div>
            )}
          </section>

          <section className="card net-card">
            <PairTable
              pairs={filtered}
              nameOf={nameOf}
              selected={selKey}
              onSelect={selectPair}
              onClear={() => setSelKey(null)}
            />
          </section>
        </div>
      )}
    </div>
  );
}
