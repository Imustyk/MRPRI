import { ApiContractError } from "../contracts";
import { getJson, getModelAnalysis, getTenderExplanation, type Tender } from "../api";
import { useRequest, type RequestState } from "../hooks";
function current<T>(request: RequestState<T>) { return !request.error && !request.stale ? request.data : null; }
export function useProcedureData(id: string) {
  const row = useRequest(id, signal => getJson<Tender>(`/api/tenders/${encodeURIComponent(id)}`, signal), Boolean(id));
  const model = useRequest(id, signal => getModelAnalysis(id, signal), Boolean(id));
  const explanation = useRequest(id, signal => getTenderExplanation(id, signal), Boolean(id));
  const tender = current(row); const analysis = current(model);
  const mismatch = tender && analysis && (analysis.tender_id !== tender.tender_id || Boolean(analysis.run_id && analysis.run_id !== tender.score_provenance?.run_id));
  const associationError = mismatch ? new ApiContractError("model-analysis.run_id/tender_id", "provenance").message : null;
  return { tender, analysis: associationError ? null : analysis, explanation: current(explanation),
    error: row.error, errorStatus: row.errorStatus, loading: Boolean(id) && (row.loading || row.stale), retry: row.reload,
    analysisError: associationError ?? model.error, analysisLoading: model.loading || model.stale, retryAnalysis: model.reload,
    explanationError: explanation.error, explanationLoading: explanation.loading || explanation.stale, retryExplanation: explanation.reload };
}
