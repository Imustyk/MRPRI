import { useState } from "react";
import { useTranslation } from "react-i18next";
import { type Tender } from "../api";
import { tr } from "../i18n/backendMap";
import { Pill } from "../ui";
import { metric } from "./ModelExplanationCard";

const INDICATORS = [
  { key: "value_vs_cpv_median", group: "financial", formula: "clip(award_value / median(award_value | CPV), 0, 20); missing → 1", inputs: "award_value, cpv_primary", quality: "award" },
  { key: "estimate_to_award_ratio", group: "financial", formula: "clip(estimated_value / award_total, 0, 20); award_total missing → award_value; missing ratio → 1", inputs: "estimated_value, award_total, award_value", quality: "estimate" },
  { key: "n_bidders", group: "competition", formula: "n_bidders (ETL)", inputs: "n_bidders, has_bid_data", quality: "bid" },
  { key: "single_bidder", group: "competition", formula: "1[n_bidders = 1]", inputs: "n_bidders", quality: "bid" },
  { key: "bid_window_days", group: "procedural", formula: "clip(floor((tender_end − tender_start) / 1 day), 0, 3650); missing → 30", inputs: "tender_start, tender_end", quality: "dates" },
  { key: "short_deadline", group: "procedural", formula: "1[0 ≤ bid_window_days < 7]", inputs: "bid_window_days", quality: "dates" },
  { key: "buyer_supplier_repeat_share", group: "behavioural", formula: "n(awarded procedures | buyer, winner) / n(awarded procedures | buyer)", inputs: "buyer_id, winner_id, award_total", quality: "pair" },
  { key: "winner_share_of_buyer_awards", group: "behavioural", formula: "n(awarded procedures | buyer, winner) / n(awarded procedures | buyer)", inputs: "buyer_id, winner_id, award_total", quality: "pair" },
] as const;
const GROUPS = ["all", "financial", "competition", "procedural", "behavioural"] as const;
const RULE_LOGIC: Record<string, string> = {
  "Single bidder": "1[n_bidders = 1]",
  "Short bidding window": "1[0 ≤ bid_window_days < 7]",
  "Long bidding window": "1[bid_window_days > 90]",
  "Accelerated procedure": "1[procurement_method_details matches accelerated|urgent|exception (case-insensitive)]",
  "No award published after tender": "1[status = complete AND award_value is missing]",
  "Award split into many lots": "1[n_awards_with_value > 1]",
  "Several suppliers on one award": "1[n_suppliers > 1]",
  "Cancelled": "1[status in {cancelled, unsuccessful}]",
  "Amended after publication": "1[n_amendments > 0]",
  "No bid data published": "1[n_bidders = 0 after ETL missing-value handling]",
};
const ACTIVE_LABELS: Record<string, string> = { single_bidder: "Single bidder", short_deadline: "Short bidding window" };

export function IndicatorPanel({ tender, plain = false }: { tender: Tender; plain?: boolean }) {
  const { t } = useTranslation();
  const [group, setGroup] = useState<string>("all");
  const flags = Array.isArray(tender.flags) ? tender.flags : [];
  return <section className="indicator-section">
    <div className="section-heading"><div><span className="eyebrow">{t("analysis.separate_rules")}</span><h2>{t(plain ? "product.why" : "analysis.indicators_title")}</h2></div></div>
    <p className="muted">{t("analysis.indicators_note")}</p>
    <div className="filter-segments" role="group" aria-label={t("analysis.indicator_group")}>
      {GROUPS.map((key) => <button key={key} type="button" aria-pressed={key === group} onClick={() => setGroup(key)}>{t(`analysis.groups.${key}`)}</button>)}
    </div>
    <div className="indicator-grid">{INDICATORS.filter((item) => group === "all" || item.group === group).map((item) => {
      const value = tender[item.key];
      const missing = value === null || value === undefined || item.quality === "bid" && tender.has_bid_data !== true;
      const incomplete = item.quality === "dates" ? !tender.tender_start || !tender.bid_deadline
        : item.quality === "estimate" ? tender.estimated_value_mdl === null || tender.award_total_mdl === null || tender.award_total_mdl === 0
        : item.quality === "award" ? tender.award_value_mdl === null
        : item.quality === "pair" ? !tender.buyer_id || !tender.winner_id : false;
      const triggered = Boolean(ACTIVE_LABELS[item.key] && flags.includes(ACTIVE_LABELS[item.key]));
      return <article className="indicator-card surface" key={item.key} data-indicator={item.key}>
        <div className="section-heading"><span className="eyebrow">{t(`analysis.groups.${item.group}`)}</span><Pill tone={missing ? "muted" : incomplete ? "warn" : "info"}>{t(missing ? "analysis.source_missing" : incomplete ? "analysis.derived_unverified" : "analysis.stored_value")}</Pill></div>
        <h3>{t(`analysis.indicators.${item.key}.title`)}</h3>
        <div className="indicator-value">{missing ? t("analysis.unavailable") : metric(value, 4)}</div>
        <p>{t(`analysis.indicators.${item.key}.description`)}</p>
        {triggered && <p><Pill tone="warn">{t("analysis.recorded_signal")}: {tr(ACTIVE_LABELS[item.key])}</Pill></p>}
        {plain && <p className="microcopy">{t(`analysis.indicators.${item.key}.limitation`)}</p>}
        <details className="research-disclosure"><summary>{t("analysis.formula_quality")}</summary>
          <h4>{t("analysis.formula")}</h4><code className="formula">{item.formula}</code>
          <h4>{t("analysis.inputs")}</h4><code className="break-anywhere">{item.inputs}</code>
          <p className="microcopy">{t("analysis.etl_value")}: {metric(value, 6)}</p>
          {!plain && <p>{t(`analysis.indicators.${item.key}.limitation`)}</p>}
          <p className="microcopy">{t("analysis.source")}: <code>src/mtender/features.py</code></p>
          <p className="microcopy">{t("analysis.no_indicator_threshold")}</p>
        </details>
      </article>;
    })}</div>
    <details className="surface research-disclosure indicator-other"><summary>{t("analysis.additional_rules")}</summary>
      <p>{t("analysis.additional_rules_note")}</p>
      <div className="recorded-rules">{flags.length ? flags.map((flag) => <div className="recorded-rule" key={flag}>
        <Pill tone="warn">{tr(flag)}</Pill>
        <p className="microcopy">{t("analysis.formula")}</p><code className="formula">{RULE_LOGIC[flag] ?? t("analysis.unavailable")}</code>
        <p className="microcopy">{t("analysis.source")}: <code>src/mtender/features.py → flags</code></p>
      </div>) : <span className="muted">{t("analysis.no_recorded_signals")}</span>}</div>
      <p className="microcopy">{t("analysis.specialized_unavailable")}</p>
    </details>
  </section>;
}
