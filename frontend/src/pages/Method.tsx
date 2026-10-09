import { getJson, type Meta } from "../api";
import { useEffect, useState } from "react";

export default function Method() {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    getJson<Meta>("/api/meta").then(setMeta).catch(() => undefined);
  }, []);

  return (
    <div>
      <div className="kicker">Thesis mapping</div>
      <h1>How the detector is built</h1>
      <p className="lede">
        The dashboard is a read-only view over the ETL in <code>/scripts</code>. Every number it
        shows comes from the real MTender OCDS feed stored in MongoDB, not from generated data.
      </p>

      <div className="card">
        <h2>Pipeline</h2>
        <ol>
          <li>
            Walk the whole public OCID history (<code>01a</code>) and fetch one OCDS package per
            procedure (<code>01b</code>), keeping the exact response body in an archive so any
            result can be recomputed.
          </li>
          <li>
            Normalise and validate (<code>02</code>): resolve the buyer from{" "}
            <code>parties[].roles</code> because the top-level <code>buyer</code> is never populated,
            read CPV from both <code>tender.classification</code> and{" "}
            <code>tender.items[].classification</code>, and accept both address layouts.
          </li>
          <li>
            Engineer indicators in SQL and pandas (<code>03</code>), with the MongoDB and pandas
            definitions of the CPV median cross-checked against each other.
          </li>
          <li>
            Score with four independent detectors (<code>06</code>): a MAD z-score baseline,
            Isolation Forest, Local Outlier Factor and One-Class SVM, each at a 5% contamination
            assumption. Binary red flags are reported separately instead of being z-scored.
          </li>
          <li>
            Export the snapshot (<code>04</code>), descriptive tables (<code>05</code>), SHAP and
            permutation importance (<code>07</code>) and a live field dictionary (<code>08</code>).
          </li>
        </ol>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2>How the risk band is set</h2>
        <p>
          A procedure is banded by how many detectors flagged it: <strong>medium</strong> = 1,{" "}
          <strong>high</strong> = 2, <strong>critical</strong> = 3 or more (consensus). Banding on
          agreement rather than on a score threshold keeps the bands comparable across models,
          whose raw score scales differ by orders of magnitude.
        </p>
        {meta && (
          <table>
            <tbody>
              {Object.entries(meta.risk_bands).map(([band, meaning]) => (
                <tr key={band}>
                  <td>
                    <span className={`badge ${band}`}>{band}</span>
                  </td>
                  <td className="muted">{meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted" style={{ marginTop: 12 }}>
          The percentile figure shown next to each band is the rank of the record's most extreme
          detector within this dataset. It is not a probability, and it is not comparable between
          different runs of the pipeline.
        </p>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2>Indicators that are deliberately absent</h2>
        <p className="muted">
          MTender does not publish these, so they are not computed and never shown as zero. An
          earlier version of this dashboard derived them from generated data, which made invented
          figures look like measurements.
        </p>
        {meta && (
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Why it is unavailable</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(meta.unavailable).map(([field, why]) => (
                <tr key={field}>
                  <td>
                    <code>{field}</code>
                  </td>
                  <td className="muted">{why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h2>What a high band means</h2>
        <p>
          The detector flags statistical and rule-based irregularities used internationally as{" "}
          <em>corruption risk indicators</em>. It does not accuse a firm or a contracting authority.
          Moldova publishes no procedure-level "corrupt / not corrupt" label, so precision and
          recall are not computable on this source: model quality is evidenced by agreement between
          independent detectors and by univariate significance testing of each indicator against
          the consensus flag, while any evaluation against known labels requires an external
          dataset.
        </p>
        <p className="muted">
          Award amounts are summed across every awarded lot before being compared with the
          estimate, because <code>estimated_value</code> covers the whole procedure while a
          procedure can be awarded in hundreds of lots.
        </p>
      </div>
    </div>
  );
}
