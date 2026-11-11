import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { createAnnotation, createCase, mtenderUrl, type Tender } from "../api";
import { AsyncForm } from "./AsyncAction";

export function ProcedureActions({ tender }: { tender: Tender }) {
  const { t } = useTranslation();
  const [caseId, setCaseId] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [noteSaved, setNoteSaved] = useState(false);
  const ocid = tender.ocid;

  return <section className="surface case-facts" id="case-actions">
    <h2>{t("product.next")}</h2>
    <div className="flags">
      {ocid && <a className="action-secondary" href={mtenderUrl(ocid)} target="_blank" rel="noreferrer noopener">{t("common.open_mtender")} ↗</a>}
      {tender.buyer_id && <Link className="action-secondary" to={`/tenders?${new URLSearchParams({ buyer: tender.buyer_id })}`}>{t("product.related")}</Link>}
    </div>
    {ocid && <>
      <details className="research-disclosure">
        <summary>{t("product.saveCase")}</summary>
        {caseId !== null ? <p role="status"><Link to={`/workspace?case=${caseId}`}>{t("product.openCase")}</Link></p> : (
          <AsyncForm onSubmit={async event => {
            const title = String(new FormData(event.currentTarget).get("title") ?? "").trim();
            if (title.length < 3) throw new Error(t("workspace.err_title_short"));
            const saved = await createCase({ title, ocids: [ocid] });
            setCaseId(saved.id);
          }}>
            <div className="toolbar">
              <label className="field grow">{t("product.caseTitle")}<input name="title" required minLength={3} maxLength={300} defaultValue={tender.title ?? ocid} /></label>
              <button type="submit">{t("common.save")}</button>
            </div>
          </AsyncForm>
        )}
      </details>
      <details className="research-disclosure">
        <summary>{t("product.addNote")}</summary>
        <AsyncForm onSubmit={async () => {
          setNoteSaved(false);
          await createAnnotation({ ocid, note: note.trim(), case_id: caseId });
          setNote("");
          setNoteSaved(true);
        }}>
          <label className="field">{t("product.note")}<textarea value={note} maxLength={8000} required onChange={event => { setNote(event.target.value); setNoteSaved(false); }} /></label>
          <button type="submit" disabled={!note.trim()}>{t("common.save")}</button>
          {noteSaved && <p role="status">{t("product.savedNote")}</p>}
        </AsyncForm>
      </details>
    </>}
  </section>;
}
