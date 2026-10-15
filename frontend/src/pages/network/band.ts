/**
 * Percentile-band encoding shared by every view on the relational page, so the
 * matrix, the ranked-pairs table, the drill-down canvas and the legend can
 * never disagree about what a colour means.
 *
 * The bands are fixed by the spec and deliberately asymmetric:
 *
 * - percentile >= 80   orange   — the band that must catch the eye first;
 * - percentile 50-79   blue-grey — distinct from both neighbours;
 * - percentile < 50    light grey;
 * - never scored       the *same* light grey, because "no detector ran" and
 *                      "detectors ran and were unimpressed" are one class for
 *                      fill purposes -- but an unscored cell/edge additionally
 *                      gets a dashed outline, so absence of model output can
 *                      never be read as a clearance by colour alone.
 *
 * Every consumer also carries the numeric percentile (tooltip, table, cell
 * label), so colour is always a redundancy, never the only channel.
 */
export const EDGE_FILL = {
  high: "#c2661f", // percentile >= 80
  mid: "#8aa0b8", // 50-79
  low: "#e4e8ed", // < 50
  unscored: "#e4e8ed", // no detector ever produced output (same fill, dashed edge)
} as const;

export type EdgeBand = keyof typeof EDGE_FILL;

/** Anomaly percentile 0-100 (or its absence) -> the band it belongs to. */
export function edgeBand(risk: number | null | undefined): EdgeBand {
  if (risk === null || risk === undefined || Number.isNaN(risk)) return "unscored";
  if (risk >= 80) return "high";
  if (risk >= 50) return "mid";
  return "low";
}

/** Unscored pairs are drawn with a dashed outline on top of the shared fill. */
export function isUnscored(band: EdgeBand): boolean {
  return band === "unscored";
}
