import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ProcedurePicker } from "../components/ProcedurePicker";
import { useProcedureData } from "../components/useProcedureData";
import { ModelWorkbench } from "../components/ModelExplanationCard";
import { IndicatorPanel } from "../components/IndicatorPanel";
import { ErrorNote, Loading, PageHead } from "../ui";

export default function ResearchAnalysis({ mode = "models" }: { mode?: "models" | "indicators" }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const id = params.get("tender") ?? "";
  const select = useCallback((value: string) => setParams({ tender: value }, { replace: true }), [setParams]);
  const data = useProcedureData(id);
  return <div className="research-page">
    <PageHead kicker={t("analysis.platform")} title={t(mode === "models" ? "analysis.models_title" : "analysis.indicators_title")} lede={t(mode === "models" ? "analysis.models_intro" : "analysis.indicators_intro")} />
    <ProcedurePicker value={id} onChange={select} />
    {data.loading && <Loading />}
    {data.error && <ErrorNote error={data.error} onRetry={data.retry} />}
    {data.tender && <>
      <div className="selected-procedure"><span className="eyebrow">{t("analysis.selected_procedure")}</span><h2>{data.tender.title ?? id}</h2><code>{id}</code></div>
      {mode === "models" ? <>
        {data.analysisError && <ErrorNote error={data.analysisError} onRetry={data.retry} />}
        {!data.analysis && !data.analysisError && <Loading />}
        {data.analysis && <ModelWorkbench tender={data.tender} analysis={data.analysis} />}
      </> : <IndicatorPanel tender={data.tender} />}
    </>}
    <p className="methodology-notice">{t("analysis.disclaimer")}</p>
  </div>;
}
