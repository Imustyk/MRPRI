import { Link } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import { getJson, type Meta } from "../api";
import { useEffect, useState } from "react";
import { PageHead } from "../ui";
import { tr } from "../i18n/backendMap";

export default function Method() {
  const { t } = useTranslation();
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    getJson<Meta>("/api/meta").then(setMeta).catch(() => undefined);
  }, []);

  return (
    <div>
      <PageHead
        kicker={t("method.kicker")}
        title={t("method.title")}
        lede={
          <Trans
            i18nKey="method.lede"
            components={{
              code: <code />,
              racilink: <Link to="/raci" />,
            }}
          />
        }
      />

      <div className="stack">
      <div className="card">
        <h2>{t("method.pipeline_h")}</h2>
        <ol>
          <li>
            <Trans i18nKey="method.pipeline.step1" components={{ code: <code /> }} />
          </li>
          <li>
            <Trans i18nKey="method.pipeline.step2" components={{ code: <code /> }} />
          </li>
          <li>
            <Trans i18nKey="method.pipeline.step3" components={{ code: <code /> }} />
          </li>
          <li>
            <Trans
              i18nKey="method.pipeline.step4"
              components={{ code: <code />, kpilink: <Link to="/kpis" /> }}
            />
          </li>
          <li>
            <Trans i18nKey="method.pipeline.step5" components={{ code: <code /> }} />
          </li>
        </ol>
      </div>

      <div className="card">
        <h2>{t("method.band_h")}</h2>
        <p>
          <Trans i18nKey="method.band_p" components={{ strong: <strong /> }} />
        </p>
        {meta && (
          <table>
            <tbody>
              {Object.entries(meta.risk_bands).map(([band, meaning]) => (
                <tr key={band}>
                  <td>
                    <span className={`badge ${band}`}>{t(`risk.${band}`)}</span>
                  </td>
                  <td className="muted">{tr(meaning)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted" style={{ marginTop: 12 }}>
          {t("method.band_note")}
        </p>
      </div>

      <div className="card">
        <h2>{t("method.absent_h")}</h2>
        <p className="muted">{t("method.absent_p")}</p>
        {meta && (
          <table>
            <thead>
              <tr>
                <th>{t("method.absent_th_field")}</th>
                <th>{t("method.absent_th_why")}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(meta.unavailable).map(([field, why]) => (
                <tr key={field}>
                  <td>
                    <code>{field}</code>
                  </td>
                  <td className="muted">{tr(why)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>{t("method.high_h")}</h2>
        <p>
          <Trans i18nKey="method.high_p" components={{ em: <em /> }} />
        </p>
        <p className="muted">
          <Trans i18nKey="method.high_p2" components={{ code: <code /> }} />
        </p>
      </div>
      </div>
    </div>
  );
}
