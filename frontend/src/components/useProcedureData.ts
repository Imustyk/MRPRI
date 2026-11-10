import { useEffect, useState } from "react";
import { getJson, getModelAnalysis, getTenderExplanation, type ModelAnalysis, type Tender, type TenderExplanation } from "../api";

/** Keep late responses for the previous selection out of the new case file. */
export function useProcedureData(id: string) {
  const [tender, setTender] = useState<Tender | null>(null);
  const [analysis, setAnalysis] = useState<ModelAnalysis | null>(null);
  const [explanation, setExplanation] = useState<TenderExplanation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(id));
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    setTender(null); setAnalysis(null); setExplanation(null); setError(null); setAnalysisError(null);
    if (!id) { setLoading(false); return; }
    setLoading(true);
    getJson<Tender>(`/api/tenders/${encodeURIComponent(id)}`, controller.signal).then((row) => {
      if (live) { setTender(row); setLoading(false); }
    }).catch((reason: Error) => { if (live) { setError(reason.message); setLoading(false); } });
    getModelAnalysis(id, controller.signal).then((value) => { if (live) setAnalysis(value); })
      .catch((reason: Error) => { if (live) setAnalysisError(reason.message); });
    getTenderExplanation(id, controller.signal).then((value) => { if (live) setExplanation(value); }).catch(() => undefined);
    return () => { live = false; controller.abort(); };
  }, [id, attempt]);
  return { tender, analysis, explanation, error, analysisError, loading, retry: () => setAttempt((n) => n + 1) };
}
