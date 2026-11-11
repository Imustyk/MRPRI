import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The composition heatmap paints with one semantic token (`--chart-heat`) mixed
 * into the card background, capped at 55% so the numbers keep AA contrast in
 * both themes. This test computes the actual mixed colours from the shipped
 * tokens (light and dark) and checks the worst case against WCAG AA.
 */

const css = readFileSync(resolve(process.cwd(), "src/product.css"), "utf8");

function tokensIn(block: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const match of block.matchAll(/--([\w-]+):\s*([^;]+);/g)) {
    out[match[1]] = match[2].trim();
  }
  return out;
}

function blockAfter(marker: string): string {
  const start = css.indexOf(marker);
  expect(start, `marker ${marker} present in product.css`).toBeGreaterThanOrEqual(0);
  const end = css.indexOf("}", start);
  return css.slice(start, end);
}

function hex(value: string): [number, number, number] {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value.trim());
  if (!m) throw new Error(`not a hex colour: ${value}`);
  const digits = m[1].length === 3 ? m[1].split("").map((c) => c + c).join("") : m[1];
  const n = parseInt(digits, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function mix(a: [number, number, number], b: [number, number, number], share: number): [number, number, number] {
  return [
    Math.round(a[0] * share + b[0] * (1 - share)),
    Math.round(a[1] * share + b[1] * (1 - share)),
    Math.round(a[2] * share + b[2] * (1 - share)),
  ];
}

function luminance([r, g, b]: [number, number, number]): number {
  const channel = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(fg: [number, number, number], bg: [number, number, number]): number {
  const l1 = luminance(fg);
  const l2 = luminance(bg);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

const light = tokensIn(blockAfter(":root {"));
const dark = tokensIn(blockAfter(':root[data-theme="dark"]'));

describe("heatmap readability (WCAG AA)", () => {
  for (const [name, theme] of [
    ["light", light],
    ["dark", dark],
  ] as const) {
    it(`${name}: ink stays ≥ 4.5:1 over a cell at maximum intensity (55%)`, () => {
      const card = hex(theme["card"]);
      const ink = hex(theme["ink"]);
      const heat = hex(theme["chart-heat"]);
      for (const intensity of [0, 25, 55]) {
        const cell = mix(heat, card, intensity / 100);
        expect(
          contrast(ink, cell),
          `${name} theme at ${intensity}% intensity`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    });

    it(`${name}: the heat token is distinct from the card at full strength`, () => {
      const card = hex(theme["card"]);
      const heat = hex(theme["chart-heat"]);
      // Otherwise every cell would look identical regardless of the count.
      expect(contrast(heat, card)).toBeGreaterThan(1.4);
    });
  }

  it("the heatmap intensity cap in Distributions is the 55% this test verifies", () => {
    const source = readFileSync(resolve(process.cwd(), "src/pages/Distributions.tsx"), "utf8");
    expect(source).toMatch(/\*\s*55\)/);
    expect(source).toContain("var(--chart-heat)");
  });
});

