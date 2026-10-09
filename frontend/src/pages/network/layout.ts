import type { GraphLink, GraphNode } from "../../api";

export type Placed = { x: number; y: number; r: number };

/**
 * Layout for the buyer-winner network.
 *
 * Why a force layout at all
 * -------------------------
 * The previous page put nodes on two hard-coded concentric circles, which
 * overlaps and crosses badly once the payload exceeds a few dozen parties. A
 * Fruchterman-Reingold layout lets the data set the geometry: authorities and
 * suppliers settle into a mild left/right ordering, heavily awarded parties
 * pull their partners inwards, and a collision pass removes the overlaps a
 * purely attractive model leaves behind.
 *
 * Why it stays fast on 150k rows of history
 * -----------------------------------------
 * Repulsion -- the ``k^2 / d`` term, the O(N^2) part of any force layout -- is
 * evaluated only inside a 3x3 neighbourhood of a grid whose cells are ``2k``
 * wide. That covers the ~3k surroundings that actually matter (past that the
 * term contributes under a third of a typical force) while cutting ~61k pair
 * evaluations per pass at 350 nodes down to ~9k, which is what keeps a full
 * layout near 120ms and makes re-laying out on every filter change acceptable.
 *
 * Why ``fit`` scales the radii too
 * --------------------------------
 * The natural layout does not always match the viewport's aspect ratio. Shrinking
 * only the coordinates would drag nodes past each other while their outlines
 * stayed the same size -- observed as 1,300+ overlapping pairs on a 1,024-node
 * slice. Scaling positions *and* radii by one factor is a plain zoom-out: it
 * preserves every distance ratio, so it cannot introduce a single new overlap.
 *
 * Everything is deterministic: positions start on a golden-angle spiral keyed to
 * node order, so the same payload always draws the same picture.
 */

/** Force passes over the whole graph. */
const ITER = 400;
/** Fruchterman-Reingold repulsion: force is ``k^2 / d``. */
const REPULSION = 1;
/** Edge attraction: ``d^2 / k``. The two balance exactly at ``d == k``. */
const SPRING = 1;
/**
 * Pulls each role toward its own column. Deliberately weak: at 0.12 it beat the
 * edge attraction, collapsed the two roles onto each other and squeezed a
 * 1,160x640 drawing into a 300px-wide ribbon.
 */
const ROLE_PULL = 0.015;
/** Vertical centring. Horizontal containment comes from ROLE_PULL. */
const CENTER_PULL = 0.1;
/** Extra push applied while two circles still overlap. */
const OVERLAP_PUSH = 6;
/** Clearance kept between two node outlines. */
const MIN_GAP = 4;
/** Overlap-resolution passes run before and after the final fit. */
const COLLIDE_PASS = 80;
/**
 * Cap on how far one pair's correction may move a node. Overshooting is what
 * makes simultaneous overlap removal oscillate; a small cap keeps each pass
 * monotone.
 */
const MAX_STEP = 6;
/** Bounds the final zoom so a sparse graph cannot balloon into huge dots. */
const FIT_MIN = 0.5;
const FIT_MAX = 1.6;
/** Fraction of the viewport the node outlines are allowed to occupy. */
const AREA_BUDGET = 0.34;

/**
 * Node size follows how much the party was awarded, not how many edges it has.
 * A dense slice additionally shrinks every radius so the outlines fit the canvas
 * at all: 1,024 nodes at the default sizes would need more room than exists.
 */
function radiiFor(nodes: GraphNode[], width: number, height: number): Float64Array {
  const count = nodes.length;
  const radii = new Float64Array(count);
  let maxAwards = 1;
  for (const n of nodes) if (n.awards > maxAwards) maxAwards = n.awards;

  let area = 0;
  for (let i = 0; i < count; i++) {
    const share = maxAwards > 0 ? Math.sqrt(Math.max(0, nodes[i].awards) / maxAwards) : 0;
    radii[i] = Math.max(4.5, Math.min(18, 4.5 + 9 * share));
    area += Math.PI * radii[i] * radii[i];
  }

  const budget = AREA_BUDGET * width * height;
  if (area > budget) {
    const shrink = Math.sqrt(budget / area);
    for (let i = 0; i < count; i++) radii[i] = Math.max(3, radii[i] * shrink);
  }
  return radii;
}

type World = {
  count: number;
  xs: Float64Array;
  ys: Float64Array;
  radii: Float64Array;
  side: Float64Array;
  left: Int32Array;
  right: Int32Array;
  fx: Float64Array;
  fy: Float64Array;
  k: number;
  width: number;
  height: number;
};

const CELL_STRIDE = 8192;
const CELL_OFFSET = 4096;

function cellKey(cx: number, cy: number): number {
  return (cy + CELL_OFFSET) * CELL_STRIDE + (cx + CELL_OFFSET);
}

/** Split nodes into grid buckets. Rebuilt every pass: positions change. */
/**
 * Grid pitch for the local-repulsion and collision passes.
 *
 * It must be at least ``2r + gap`` wide: a pair is only ever examined when the
 * two nodes land in the same or an adjacent cell, so a pitch smaller than the
 * largest possible clearance would let two big nodes sit on top of each other
 * in cells two apart and never be looked at -- which is exactly how a 1,024-node
 * slice kept two overlaps after reporting every pass clean.
 */
function pitchFor(w: World): number {
  let maxR = 0;
  for (let i = 0; i < w.count; i++) if (w.radii[i] > maxR) maxR = w.radii[i];
  return Math.max(24, w.k * 2, 2 * maxR + MIN_GAP + 1);
}

function bucketize(
  xs: Float64Array,
  ys: Float64Array,
  count: number,
  invCell: number,
): Map<number, number[]> {
  const buckets = new Map<number, number[]>();
  for (let i = 0; i < count; i++) {
    const key = cellKey(Math.floor(xs[i] * invCell), Math.floor(ys[i] * invCell));
    const bucket = buckets.get(key);
    if (bucket) bucket.push(i);
    else buckets.set(key, [i]);
  }
  return buckets;
}

function build(
  nodes: GraphNode[],
  links: GraphLink[],
  width: number,
  height: number,
): World | null {
  const count = nodes.length;
  if (count === 0 || width < 80 || height < 80) return null;

  const xs = new Float64Array(count);
  const ys = new Float64Array(count);
  const side = new Float64Array(count);
  const index = new Map<string, number>();
  const cx0 = width / 2;
  const cy0 = height / 2;
  const roleOffset = width * 0.18;
  const spread = Math.min(width, height) * 0.3;

  for (let i = 0; i < count; i++) {
    const node = nodes[i];
    index.set(node.id, i);
    // Golden-angle spiral: evenly spread, never coincident, and identical
    // between runs, so a filter change re-lays out from a known state.
    const angle = i * 2.399963229728653;
    const radius = spread * Math.sqrt((i + 0.5) / count);
    const roleX = node.kind === "buyer" ? cx0 - roleOffset : cx0 + roleOffset;
    xs[i] = roleX + Math.cos(angle) * radius;
    ys[i] = cy0 + Math.sin(angle) * radius;
    side[i] = node.kind === "buyer" ? -1 : 1;
  }

  const left: number[] = [];
  const right: number[] = [];
  for (const link of links) {
    const a = index.get(link.source);
    const b = index.get(link.target);
    if (a === undefined || b === undefined || a === b) continue;
    left.push(a);
    right.push(b);
  }

  return {
    count,
    xs,
    ys,
    radii: radiiFor(nodes, width, height),
    side,
    left: Int32Array.from(left),
    right: Int32Array.from(right),
    fx: new Float64Array(count),
    fy: new Float64Array(count),
    // FR's equilibrium distance. Derived from the canvas so a denser payload
    // tightens instead of overflowing it, with a floor so tiny slices do not
    // collapse onto a point.
    k: Math.max(10, Math.min(72, 0.5 * Math.sqrt((width * height) / count))),
    width,
    height,
  };
}

/** One force pass: local repulsion, edge attraction, role and centring pulls. */
function relax(w: World, temp: number, cell: number): void {
  const { count, xs, ys, radii, side, left, right, fx, fy, k, width, height } = w;
  const invCell = 1 / cell;
  const buckets = bucketize(xs, ys, count, invCell);

  fx.fill(0);
  fy.fill(0);

  for (let i = 0; i < count; i++) {
    const cxi = Math.floor(xs[i] * invCell);
    const cyi = Math.floor(ys[i] * invCell);
    for (let ox = -1; ox <= 1; ox++) {
      for (let oy = -1; oy <= 1; oy++) {
        const bucket = buckets.get(cellKey(cxi + ox, cyi + oy));
        if (!bucket) continue;
        for (let b = 0; b < bucket.length; b++) {
          const j = bucket[b];
          if (j <= i) continue;
          let dx = xs[i] - xs[j];
          let dy = ys[i] - ys[j];
          let d2 = dx * dx + dy * dy;
          if (d2 < 1e-6) {
            // Coincident nodes: give them a direction to separate along instead
            // of dividing by zero and poisoning the layout with NaN.
            dx = ((i * 7919) % 13) - 6 + 0.5;
            dy = ((j * 6271) % 11) - 5 + 0.5;
            d2 = dx * dx + dy * dy;
          }
          const d = Math.sqrt(d2);
          let mag = (REPULSION * k * k) / d;
          const minD = radii[i] + radii[j] + MIN_GAP;
          if (d < minD) mag += (minD - d) * OVERLAP_PUSH;
          const s = mag / d;
          fx[i] += dx * s;
          fy[i] += dy * s;
          fx[j] -= dx * s;
          fy[j] -= dy * s;
        }
      }
    }

    const targetX = side[i] < 0 ? width * 0.3 : width * 0.7;
    fx[i] += (targetX - xs[i]) * ROLE_PULL;
    fy[i] += (height / 2 - ys[i]) * CENTER_PULL;
  }

  for (let e = 0; e < left.length; e++) {
    const a = left[e];
    const b = right[e];
    let dx = xs[b] - xs[a];
    let dy = ys[b] - ys[a];
    let d = Math.sqrt(dx * dx + dy * dy);
    if (d < 1e-6) {
      dx = 1;
      dy = 0;
      d = 1;
    }
    // FR attraction grows with distance, which is what stops the two role
    // columns being pulled apart forever by ROLE_PULL.
    const s = (SPRING * d * d) / k / d;
    fx[a] += dx * s;
    fy[a] += dy * s;
    fx[b] -= dx * s;
    fy[b] -= dy * s;
  }

  for (let i = 0; i < count; i++) {
    const len = Math.hypot(fx[i], fy[i]);
    if (len < 1e-9) continue;
    const step = Math.min(len, temp) / len;
    xs[i] += fx[i] * step;
    ys[i] += fy[i] * step;
  }
}

/**
 * Overlap resolution only, in Gauss-Seidel form: each clashing pair is pushed
 * apart *immediately* so the next pair sees the corrected positions.
 *
 * The simultaneous variant (accumulate every force, move once at the end) is
 * the obvious translation of the force pass, and it does not converge here: on
 * a 1,024-node slice it oscillated around ~1,600 clashing pairs for all 80
 * passes instead of reducing them, because two neighbours of the same node
 * undo each other's correction every round. Returns how many pairs were still
 * inside the clearance when the pass began, so a clean layout stops after one
 * look instead of burning the full budget.
 */
function collide(w: World, cell: number): number {
  const { count, xs, ys, radii } = w;
  const invCell = 1 / cell;
  const buckets = bucketize(xs, ys, count, invCell);
  let clashes = 0;

  for (let i = 0; i < count; i++) {
    const cxi = Math.floor(xs[i] * invCell);
    const cyi = Math.floor(ys[i] * invCell);
    for (let ox = -1; ox <= 1; ox++) {
      for (let oy = -1; oy <= 1; oy++) {
        const bucket = buckets.get(cellKey(cxi + ox, cyi + oy));
        if (!bucket) continue;
        for (let b = 0; b < bucket.length; b++) {
          const j = bucket[b];
          if (j <= i) continue;
          let dx = xs[i] - xs[j];
          let dy = ys[i] - ys[j];
          let d2 = dx * dx + dy * dy;
          const minD = radii[i] + radii[j] + MIN_GAP;
          if (d2 >= minD * minD) continue;
          clashes++;
          if (d2 < 1e-6) {
            // Coincident nodes: give them a direction to separate along instead
            // of dividing by zero and producing NaN coordinates.
            dx = ((i * 7919) % 13) - 6 + 0.5;
            dy = ((j * 6271) % 11) - 5 + 0.5;
            d2 = dx * dx + dy * dy;
          }
          const d = Math.sqrt(d2);
          const move = Math.min(((minD - d) * 0.5), MAX_STEP);
          const sx = (dx / d) * move;
          const sy = (dy / d) * move;
          xs[i] += sx;
          ys[i] += sy;
          xs[j] -= sx;
          ys[j] -= sy;
        }
      }
    }
  }
  return clashes;
}

function settle(w: World, cell: number): void {
  for (let pass = 0; pass < COLLIDE_PASS; pass++) {
    if (collide(w, cell) === 0) break;
  }
}

/**
 * Uniform zoom-out so the drawing fits the viewport.
 *
 * Both coordinates and radii are multiplied by the same factor, which is what
 * makes this overlap-safe: every pairwise distance and every outline shrink in
 * step, so ``d < r1 + r2`` is preserved exactly rather than created.
 */
function fit(w: World, pad: number): void {
  const { count, xs, ys, radii, width, height } = w;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (let i = 0; i < count; i++) {
    minX = Math.min(minX, xs[i] - radii[i]);
    maxX = Math.max(maxX, xs[i] + radii[i]);
    minY = Math.min(minY, ys[i] - radii[i]);
    maxY = Math.max(maxY, ys[i] + radii[i]);
  }
  const bw = maxX - minX;
  const bh = maxY - minY;
  if (!Number.isFinite(bw) || !Number.isFinite(bh) || bw <= 0 || bh <= 0) return;

  const scale = Math.max(
    FIT_MIN,
    Math.min(FIT_MAX, (width - 2 * pad) / bw, (height - 2 * pad) / bh),
  );
  if (!Number.isFinite(scale)) return;

  const offsetX = (width - bw * scale) / 2 - minX * scale;
  const offsetY = (height - bh * scale) / 2 - minY * scale;
  for (let i = 0; i < count; i++) {
    xs[i] = xs[i] * scale + offsetX;
    ys[i] = ys[i] * scale + offsetY;
    radii[i] = radii[i] * scale;
  }
}

/**
 * Placement for every node in pixel space of a ``width x height`` viewport.
 *
 * Returns the radius alongside the position: it is part of the layout, not a
 * property of the party, because dense slices shrink it to fit the canvas.
 */
export function layoutGraph(
  nodes: GraphNode[],
  links: GraphLink[],
  width: number,
  height: number,
): Map<string, Placed> {
  const w = build(nodes, links, width, height);
  const out = new Map<string, Placed>();
  if (!w) return out;

  const cell = pitchFor(w);
  const temp0 = w.k * 1.1;
  for (let iter = 0; iter < ITER; iter++) {
    relax(w, Math.max(temp0 * (1 - iter / ITER), 0), cell);
  }

  settle(w, cell);
  fit(w, 24);
  // The zoom changed every radius, so the pitch that guarantees "clashing pairs
  // are always adjacent in the grid" has to be recomputed for the final space.
  settle(w, pitchFor(w));

  for (let i = 0; i < w.count; i++) {
    out.set(nodes[i].id, { x: w.xs[i], y: w.ys[i], r: w.radii[i] });
  }
  return out;
}
