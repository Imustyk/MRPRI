import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { int, pct } from "../api";
import { intlLocale } from "../i18n";
import { PageHead } from "../ui";
import evidence from "../data/researchEvidence.json";

const methods = [
  { key: "mad", name: "MAD", explanation: "mad" },
  { key: "isolation_forest", name: "Isolation Forest", explanation: "forest" },
  { key: "lof", name: "Local Outlier Factor (LOF)", explanation: "lof" },
  { key: "one_class_svm", name: "One-Class SVM", explanation: "svm" },
] as const;

function decimal(value: number, digits: number) {
  return new Intl.NumberFormat(intlLocale(), { maximumFractionDigits: digits }).format(value);
}

function EvidenceBar({ label, value, fill, secondary = false, reference = false }: {
  label: string;
  value: string;
  fill: number;
  secondary?: boolean;
  reference?: boolean;
}) {
  return <div className={`evidence-bar${secondary ? " evidence-bar-secondary" : ""}`}>
    <div className="evidence-bar-label"><span>{label}</span><strong>{value}</strong></div>
    <div className="evidence-bar-track" aria-hidden="true">
      <span style={{ width: `${fill * 100}%` }} />
      {reference && <i className="evidence-bar-reference" />}
    </div>
  </div>;
}

export default function ResearchEvidence() {
  const { t } = useTranslation();
  const text = (key: keyof typeof import("../i18n/locales/en/researchEvidence").default) => t(`researchEvidence.${key}`);
  const largestCount = Math.max(...evidence.flags.flatMap(row => [row.legacy, row.stage]));

  return <div className="research-evidence">
    <PageHead title={text("title")} lede={text("lede")} actions={
      <Link className="action-primary" to="/tenders?level=critical">{text("open")}</Link>
    } />

    <section className="surface">
      <h2>{text("process")}</h2>
      <ol className="evidence-process">
        <li>{text("stepData")}</li>
        <li>{text("stepModels")}</li>
        <li>{text("stepReview")}</li>
      </ol>
      <h3>{text("methods")}</h3>
      <dl className="evidence-methods">
        {methods.map(method => <div key={method.key}>
          <dt>{method.name}</dt><dd>{text(method.explanation)}</dd>
        </div>)}
      </dl>
      <Link to="/models">{text("inspect")}</Link>
    </section>

    <figure className="surface evidence-figure">
      <figcaption>
        <h2>{text("flags")}</h2>
        <p className="muted">{t("researchEvidence.flagsLead", { n: int(evidence.corpus) })}</p>
      </figcaption>
      <div className="evidence-comparisons">
        {evidence.flags.map(row => <div key={row.method} className="evidence-comparison">
          <h3>{methods.find(method => method.key === row.method)?.name ?? text("ensemble")}</h3>
          <EvidenceBar label={text("legacy")} value={int(row.legacy)} fill={row.legacy / largestCount} />
          <EvidenceBar label={text("stage")} value={int(row.stage)} fill={row.stage / largestCount} secondary />
        </div>)}
      </div>
      <p className="microcopy">{text("flagsNote")}</p>
    </figure>

    <figure className="surface evidence-figure">
      <figcaption>
        <h2>{text("overlap")}</h2>
        <p className="muted">{t("researchEvidence.overlapLead", {
          rho: decimal(evidence.spearman, 3),
          jaccard: decimal(evidence.jaccard, 3),
        })}</p>
      </figcaption>
      {evidence.overlap.map(row => <EvidenceBar key={row.k}
        label={t("researchEvidence.top", { k: int(row.k) })}
        value={`${int(row.intersection)} / ${int(row.k)} · ${pct(row.intersection / row.k)}`}
        fill={row.intersection / row.k}
      />)}
      <p className="microcopy">{t("researchEvidence.overlapNote", { n: evidence.overlap[0].intersection })}</p>
    </figure>

    <figure className="surface evidence-figure">
      <figcaption>
        <h2>{text("external")}</h2>
        <p className="muted">{text("externalLead")}</p>
      </figcaption>
      <div className="evidence-comparisons">
        {evidence.external.map(row => <div key={row.target} className="evidence-comparison">
          <h3>{row.target === "aap" ? text("aap") : text("ansc")}</h3>
          {(["rank", "amount"] as const).map(key => {
            const [value, low, high] = row[key];
            return <div key={key}>
              <EvidenceBar label={text(key)} value={decimal(value, 4)} fill={value} secondary={key === "amount"} reference />
              <p className="microcopy">{t("researchEvidence.interval", { low: decimal(low, 4), high: decimal(high, 4) })}</p>
            </div>;
          })}
        </div>)}
      </div>
      <p>{text("externalNote")}</p>
    </figure>

    <p className="callout info">{text("scope")}</p>
    <details className="surface research-disclosure">
      <summary>{text("sources")}</summary>
      <ul className="evidence-source-list">
        <li><code>results/mta0025_closed_experiment/experiment_summary.json</code></li>
        <li><code>reports/MTA-0026_EXPERIMENT_VERIFICATION.md</code></li>
        <li><code>reports/thesis_revision_2026_11/THESIS_FULL_REVISED_DRAFT.md</code></li>
      </ul>
    </details>
  </div>;
}
