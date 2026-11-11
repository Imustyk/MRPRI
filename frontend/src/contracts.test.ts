import { describe, expect, it, vi, afterEach } from "vitest";
import { assertApiData } from "./contracts";
import { getJson, getTenderExplanation, send } from "./api";
import { safeReturnTo, savedViewDestination, tenderDestination } from "./navigation";
import { readDrillHash } from "./pages/network/presentation";
import "./i18n";
afterEach(() => vi.unstubAllGlobals());
describe("API semantic boundaries", () => {
  it.each([{risk_score:101},{score_percentile:-1},{n_models_flagging:1.5},{n_models_flagging:5},{n_tenders:"many"},{model_flags:{mad:1}},{iso_score:Infinity},{rule_score:-1}])("rejects invalid payload %j without changing it", value => {
    const before = {...value}; expect(() => assertApiData("/api/tenders/x", value)).toThrow(/contract/i); expect(value).toEqual(before);
  });
  it("preserves zeros, false, null and detector-specific unbounded scales", () => {
    const value = {risk_score:0,n_models_flagging:0,model_flags:{mad:false,lof:null},consensus_flag:false,iso_score:-3,svm_score:201,lof_score:200,rule_score:15,n_bidders:0};
    expect(() => assertApiData("/api/tenders/x", value)).not.toThrow(); expect(value.risk_score).toBe(0); expect(value.model_flags.lof).toBeNull();
  });
  it.each([404,422,500])("keeps HTTP %i distinct", async status => { vi.stubGlobal("fetch", vi.fn(async () => new Response('{"detail":"failure"}',{status}))); await expect(getJson("/api/stats")).rejects.toMatchObject({status}); });
  it.each(["", "{broken"]) ("terminates invalid response %j", async body => {vi.stubGlobal("fetch", vi.fn(async () => new Response(body))); await expect(getJson("/api/stats")).rejects.toThrow();});
  it("does not relabel contract errors as malformed JSON", async () => {vi.stubGlobal("fetch", vi.fn(async () => Response.json({risk_score:999}))); await expect(getJson("/api/tenders/x")).rejects.toMatchObject({name:"ApiContractError"});});
  it("explanation 404 is unavailable; 500 remains an error", async () => {vi.stubGlobal("fetch", vi.fn(async () => new Response("",{status:404}))); await expect(getTenderExplanation("x")).resolves.toBeNull();vi.stubGlobal("fetch", vi.fn(async () => new Response("failed",{status:500})));await expect(getTenderExplanation("x")).rejects.toMatchObject({status:500});});
  it("mutation malformed JSON is actionable", async () => {vi.stubGlobal("fetch", vi.fn(async () => new Response("broken"))); await expect(send("POST","/api/workspace/cases",{})).rejects.toThrow(/malformed/i);});
});
describe("safe navigation and legacy views", () => {
  it.each(["https://evil.invalid/tenders","//evil.invalid/tenders","/tenders/x","/tenders#bad","/tenders?x=%zz","/tenders\\evil"]) ("blocks unsafe return %s", value => expect(safeReturnTo(value)).toBe("/tenders"));
  it("retains the exact list context", () => {const list="/tenders?q=a%20b&level=high&procedure=open&min=80&offset=40"; expect(safeReturnTo(list)).toBe(list);expect(new URL(tenderDestination("a/b",list),"https://local.invalid").searchParams.get("returnTo")).toBe(list);});
  it("applies supported legacy fields and blocks min_value explicitly", () => {expect(savedViewDestination({level:"high",min_risk:80,offset:40}).url).toBe("/tenders?level=high&min=80&offset=40"); expect(savedViewDestination({min_value:1000})).toEqual({url:null,unsupported:["min_value"],invalid:false});});
  it.each([[],null,42,{min:101},{offset:3},{level:"corrupt"}])("blocks invalid saved view %j", value => expect(savedViewDestination(value).url).toBeNull());
  it("malformed network encoding is an explicit unavailable state", () => {expect(readDrillHash("#drill=%E0%A4%A")).toEqual({id:null,invalid:true});expect(readDrillHash("#drill=buyer%3A1").id).toBe("buyer:1");});
});

it("analytical aliases cannot disguise invalid percentiles", () => {
 expect(() => assertApiData("/api/analytics/features", {features:[{key:"risk_score", summary:{mean:999}}],categories:[]})).toThrow();
 expect(() => assertApiData("/api/analytics/scatter", {x:"risk_score",y:"price",points:[{x:101,y:1000000}]})).toThrow();
 expect(() => assertApiData("/api/analytics/scatter", {x:"risk_score",y:"price",points:[{x:0,y:1000000}]})).not.toThrow();
});

it("empty mutation success is not invented; explicit 204 remains supported", async () => {
 vi.stubGlobal("fetch",vi.fn(async()=>new Response("",{status:200})));await expect(send("POST","/api/workspace/cases",{})).rejects.toThrow(/empty/i);
 vi.stubGlobal("fetch",vi.fn(async()=>new Response(null,{status:204})));await expect(send("DELETE","/api/workspace/cases/1")).resolves.toBeUndefined();
});
it("network failures are localized and retriable",async()=>{vi.stubGlobal("fetch",vi.fn(async()=>{throw new TypeError("Failed to fetch");}));await expect(getJson("/api/stats")).rejects.toThrow(/connection/i);});

it("estimator parameters are not observation counts and histogram padding is not an observation",()=>{
 expect(()=>assertApiData("/api/tenders/x",{params:{n_jobs:-1},n_bidders:0})).not.toThrow();
 expect(()=>assertApiData("/api/analytics/distribution",{column:"risk_score",summary:{min:0,max:0,mean:0},bins:[{x0:-.5,x1:.5,n:10}],ecdf:[[0,1]],groups:[]})).not.toThrow();
});

it("meta field descriptions are not numeric observation counts", () => {
 expect(() => assertApiData("/api/meta", {unavailable:{n_bids:"Not published",n_bidders:"Missing"},risk_bands:{unscored:"No detector output"},n_tenders:2})).not.toThrow();
 expect(() => assertApiData("/api/stats", {procedure_counts:{},n_tenders:"Not published"})).toThrow();
});

it("retains evaluation feature names and signed XAI correlations", () => {
  expect(() => assertApiData("/api/evaluation", { external_labels: [{ baselines: {
    n_bidders_log: { auc: 0.51, cluster_ci: [0.49, 0.53] },
  } }] })).not.toThrow();
  expect(() => assertApiData("/api/explainability", { xai_consistency: { agreement: {
    spearman: { median: -0.6798 }, sign_agreement: { median: 0.11 },
  } } })).not.toThrow();
  expect(() => assertApiData("/api/explainability", { xai_consistency: { agreement: 0.4 } })).toThrow();
  expect(() => assertApiData("/api/tenders/x/model-analysis", { agreement: 2, detectors: [] })).toThrow();
});
