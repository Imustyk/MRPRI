import { describe, expect, it } from "vitest";
import en from "./locales/en";
import ru from "./locales/ru";
import ro from "./locales/ro";

type Tree = { [key: string]: string | Tree };

function paths(node: Tree, prefix = ""): string[] {
  return Object.entries(node).flatMap(([key, value]) =>
    typeof value === "string"
      ? [prefix + key]
      : paths(value as Tree, `${prefix}${key}.`),
  );
}

function leaves(node: Tree, prefix = ""): [string, string][] {
  return Object.entries(node).flatMap(([key, value]) =>
    typeof value === "string"
      ? [[prefix + key, value] as [string, string]]
      : leaves(value as Tree, `${prefix}${key}.`),
  );
}

describe("locale completeness", () => {
  it("RU carries every EN key (including all new request/chart strings)", () => {
    expect(paths(ru as unknown as Tree).sort()).toEqual(paths(en as unknown as Tree).sort());
  });

  it("RO carries every EN key", () => {
    expect(paths(ro as unknown as Tree).sort()).toEqual(paths(en as unknown as Tree).sort());
  });

  it("no translated string is empty in any locale", () => {
    for (const catalog of [en, ru, ro] as unknown as Tree[]) {
      const empty = leaves(catalog).filter(([, value]) => value.trim() === "");
      expect(empty).toEqual([]);
    }
  });

  it("RU and RO are actually translated, not English copies, for the new keys", () => {
    const keys = [
      "common.results_loading",
      "common.stale_marker",
      "analysis.legend_threshold",
      "analysis.hist_all_zero",
      "tenders.params_desc",
      "distributions.spread_legend_interval",
      "distributions.mix_intensity",
    ];
    const pick = (catalog: unknown, dotted: string) =>
      dotted.split(".").reduce<unknown>((node, part) => (node as Tree)[part], catalog);
    for (const key of keys) {
      const source = pick(en, key) as string;
      expect(pick(ru, key), key).not.toBe(source);
      expect(pick(ro, key), key).not.toBe(source);
    }
  });
});
