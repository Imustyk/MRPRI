/**
 * Edge encoding shared by every view on the relational page, so the network,
 * the ranked pairs and the value flow can never disagree with the legend.
 *
 * The previous palette gave the middle and the low band the *same* hex, so the
 * "50–79" and "< 50" legend swatches were indistinguishable. Four bands now
 * have four colours, and an unscored link is additionally dashed: absence of
 * model output must not be read as a clearance.
 */
export const EDGE_FILL = {
  high: "#b4232c", // percentile >= 80
  mid: "#c98a12", // 50-79
  low: "#7d8894", // < 50
  unscored: "#b6bcc4", // no detector ever produced output
} as const;

export type EdgeBand = keyof typeof EDGE_FILL;

export const BAND_LABEL: Record<EdgeBand, string> = {
  high: "≥ 80",
  mid: "50–79",
  low: "< 50",
  unscored: "not scored",
};

/** Anomaly percentile 0-100 (or its absence) -> the band it belongs to. */
export function edgeBand(risk: number | null | undefined): EdgeBand {
  if (risk === null || risk === undefined || Number.isNaN(risk)) return "unscored";
  if (risk >= 80) return "high";
  if (risk >= 50) return "mid";
  return "low";
}

export function isUnscored(band: EdgeBand): boolean {
  return band === "unscored";
}

/** ``"Contracting authority · 24 awards · percentile 81.0"`` */
export function bandStroke(band: EdgeBand): string {
  return EDGE_FILL[band];
}
