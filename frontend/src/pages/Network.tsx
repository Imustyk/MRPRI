import { useEffect, useMemo, useState } from "react";
import { getJson, mdl, num, pctile, type GraphData } from "../api";
import { Empty, ErrorNote, Skeleton, TableWrap } from "../ui";

const W = 920;
const H = 560;

/** Same scale the rest of the dashboard uses: an anomaly percentile, 0-100. */
const EDGE_FILL = { high: "#c2661f", mid: "#8aa0b8", low: "#8aa0b8" } as const;

function edgeBand(maxRisk: number | null): keyof typeof EDGE_FILL {
  // An unscored link must not be painted as low risk, so it gets the neutral tone.
  if (maxRisk === null) return "low";
  if (maxRisk >= 80) return "high";
  if (maxRisk >= 50) return "mid";
  return "low";
}

export default function Network() {
  const [g, setG] = useState<GraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    getJson<GraphData>("/api/graph")
      .then((d) => {
        setG(d);
        setLoading(false);
      })
      .catch((e: Error) => {
        setError(e.message);
        setLoading(false);
      });
  };

  useEffect(load, []);

  const layout = useMemo(() => {
    if (!g) return [];
    const buyers = g.nodes.filter((n) => n.kind === "buyer");
    const bidders = g.nodes.filter((n) => n.kind !== "buyer");
    const pos = new Map<string, { x: number; y: number; node: (typeof g.nodes)[number] }>();
    buyers.forEach((n, i) => {
      const t = (i / Math.max(buyers.length, 1)) * Math.PI * 2;
      pos.set(n.id, { x: 280 + Math.cos(t) * 160, y: H / 2 + Math.sin(t) * 160, node: n });
    });
    bidders.forEach((n, i) => {
      const t = (i / Math.max(bidders.length, 1)) * Math.PI * 2;
      pos.set(n.id, { x: W / 2 + 80 + Math.cos(t) * 250, y: H / 2 + Math.sin(t) * 240, node: n });
    });
    return [...pos.values()];
  }, [g]);

  if (loading) {
    return (
      <div>
        <h1>Buyer–winner network</h1>
        <Skeleton rows={8} height={28} />
      </div>
    );
  }

  if (error || !g) {
    return (
      <div>
        <h1>Buyer–winner network</h1>
        <ErrorNote error={error ?? "No graph returned."} onRetry={load} />
      </div>
    );
  }

  const posMap = new Map(layout.map((p) => [p.node.id, p]));
  const nameOf = (id: string) => g.nodes.find((n) => n.id === id)?.name ?? id;
  const ranked = [...g.links].sort(
    (a, b) => (b.max_risk ?? -1) - (a.max_risk ?? -1) || b.weight - a.weight,
  );

  if (g.links.length === 0) {
    return (
      <div>
        <div className="kicker">Relational layer</div>
        <h1>Buyer–winner network</h1>
        <Empty
          title="No repeated buyer–winner pairs"
          hint="An edge needs a supplier that won more than one procedure from the same authority."
        />
      </div>
    );
  }

  return (
    <div>
      <div className="kicker">Relational layer</div>
      <h1>Buyer–winner network</h1>
      <p className="lede">
        An edge is a supplier that won repeatedly from the same authority. Thickness follows the
        number of awards on that pair; colour follows the highest anomaly percentile recorded for
        it.
      </p>

      <ul className="legend">
        <li>
          <span className="swatch" style={{ background: "#1e3a5f" }} /> contracting authority
        </li>
        <li>
          <span className="swatch" style={{ background: "#b8892a" }} /> supplier
        </li>
        <li>
          <span className="swatch line" style={{ background: EDGE_FILL.high }} /> percentile ≥ 80
        </li>
        <li>
          <span className="swatch line" style={{ background: EDGE_FILL.mid }} /> 50–79
        </li>
        <li>
          <span className="swatch line" style={{ background: EDGE_FILL.low }} /> &lt; 50 or unscored
        </li>
      </ul>

      <div className="card" style={{ padding: 12 }}>
        {/* viewBox + width 100% so the graph scales down instead of forcing a
            horizontal scrollbar on a phone. */}
        <svg
          viewBox={`0 0 ${W} ${H}`}
          style={{ width: "100%", height: "auto", display: "block" }}
          role="img"
          aria-label={`Procurement network: ${g.nodes.length} organisations and ${g.links.length} repeated buyer-supplier relationships`}
        >
          {g.links.map((l) => {
            const a = posMap.get(l.source);
            const b = posMap.get(l.target);
            if (!a || !b) return null;
            return (
              <line
                key={`${l.source}-${l.target}`}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={EDGE_FILL[edgeBand(l.max_risk)]}
                strokeWidth={Math.min(8, 1 + l.weight)}
                strokeOpacity={0.7}
              >
                <title>
                  {`${nameOf(l.source)} → ${nameOf(l.target)} · ${l.weight} awards · percentile ${
                    l.max_risk === null ? "n/a" : pctile(l.max_risk)
                  }`}
                </title>
              </line>
            );
          })}
          {layout.map(({ x, y, node }) => (
            <g key={node.id}>
              <circle
                cx={x}
                cy={y}
                r={node.kind === "buyer" ? 8 : 5}
                className={node.kind === "buyer" ? "node-buyer" : "node-bidder"}
              >
                <title>{`${node.name} (${node.kind}, ${node.locality})`}</title>
              </circle>
            </g>
          ))}
        </svg>
        <p className="muted" style={{ marginTop: 10 }}>
          Hover any edge or node for detail. The table below carries the same{" "}
          {g.links.length} relationships without relying on colour or hover.
        </p>
      </div>

      <h2 style={{ marginTop: 24 }}>Relationships by anomaly percentile</h2>
      <TableWrap wide>
        <table>
          <thead>
            <tr>
              <th scope="col">Authority</th>
              <th scope="col">Supplier</th>
              <th scope="col">Awards</th>
              <th scope="col">Total value</th>
              <th scope="col">Max percentile</th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((l) => (
              <tr key={`${l.source}-${l.target}`}>
                <td>{nameOf(l.source)}</td>
                <td>{nameOf(l.target)}</td>
                <td className="mono">{num(l.weight)}</td>
                <td className="mono">{mdl(l.value)}</td>
                <td className="mono">{pctile(l.max_risk)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableWrap>
    </div>
  );
}
