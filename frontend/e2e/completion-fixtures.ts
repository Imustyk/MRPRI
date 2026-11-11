import {expect, type Page} from "@playwright/test";
export const id = "ocds-test-001";
export const tender = {tender_id:id,ocid:id,title:"TEST ONLY: procurement",buyer_name:"Test authority",buyer_id:"b1",risk_score:80,risk_level:"high",n_models_flagging:2,model_flags:{statistical_mad_zscore:true,isolation_forest:false,local_outlier_factor:true,one_class_svm:null},consensus_flag:false,iso_score:-2,lof_score:3,svm_score:null,rule_score:11,flags:[],procedure:"open",procurement_method:"open",status:"active",published_at:"2023-01-01",bid_deadline:"2023-02-01",bid_window_days:31,estimated_value_mdl:100,award_total_mdl:80,award_value_mdl:80,has_bid_data:false,has_award_data:true,cpv_code:"123",buyer_locality:null,buyer_identifier:null,winner_name:null,winner_idno:null,n_bidders:null,n_bid_records:null,n_lots:1,n_awards:1,single_bidder:null,short_deadline:null,value_vs_cpv_median:null,winner_share_of_buyer_awards:null,buyer_supplier_repeat_share:null,estimate_to_award_ratio:1.25,score_provenance:{run_id:"test-run",source:"test fixture"}};
const keys=["statistical_mad_zscore","isolation_forest","local_outlier_factor","one_class_svm"];
export const analysis={tender_id:id,run_id:"test-run",source:"isolated test fixture",summary_matches_run:true,generated_at:"2026-01-01",model_version:"test",n_reference:10,n_corpus:10,scope:"same_run_available_scores",detectors:keys.map((key,i)=>({key,label:["MAD","Isolation Forest","LOF","One-Class SVM"][i],field:["mad_zscore","if_score","lof_score","svm_score"][i],score:[11,-2,3,0][i],verdict:i===0||i===2?"flagged":"not_flagged",n_reference:10,n_missing_score:0,score_percentile:80,bins:[{index:0,start:-5,end:0,n:3,selected:i===1},{index:1,start:0,end:10,n:4,selected:i>=2},{index:2,start:10,end:15,n:3,selected:i===0}],threshold:i===0?{value:10.5,operator:">",source:"isolated fixture"}:null,threshold_matches_verdict:null,params:{},features:[],training_medians:null,training_mad:null,local_attribution:null})),agreement:keys.map(left=>keys.map(right=>({left,right,n:10,n_agree:8,agreement:.8}))),consensus:{n_models_flagging:2,flag:false,band:"high",percentile:80}};
export const explanation={tender_id:id,ocid:id,model_version:"test",scoring_run_id:"test-run",scoring_generated_at:null,consensus:{band:"high",risk_score:80,n_models_flagging:2},layers:[{id:"facts",items:[{field:"n_lots",label:"n_lots",value:1,percentile:50}]}],disclaimer:"TEST ONLY"};
export const stats={n_tenders:2,n_buyers:1,n_winners:1,total_award_mdl:160,high_risk_count:1,high_risk_value_mdl:80,single_bidder_share:null,mean_n_bidders:null,mean_n_bid_records:null,n_with_bid_data:0,mean_risk:80,level_counts:{high:1,unscored:1},procedure_counts:{open:2},top_cpv:[],monthly:[],top_risky_buyers:[],metrics:{available:false,reason:"test only"},features:[],snapshot_cohorts:{date_field:"published_at",source_field:"date",timezone:"UTC",interpretation:"retrospective_snapshot_cohorts",publication_time_certified:false,n_total:2,n_dated:2,n_scored:1,n_missing_date:0,n_invalid_date:0,monthly:[{month:"2023-01",n:2,n_scored:1,n_unscored:1,avg_risk:80}]}};
export const graph={nodes:[{id:"b1",kind:"buyer",name:"Test buyer",locality:"",degree:1,awards:4,value:100,max_risk:80,n_partners:1},{id:"s1",kind:"supplier",name:"Test supplier",locality:"",degree:1,awards:4,value:100,max_risk:80,n_partners:1}],links:[{source:"b1",target:"s1",weight:4,value:100,max_risk:80}],stats:{limit:1500,min_awards:1,min_risk:null,sort:"awards",pairs_all:1,pairs_repeated:1,pairs_qualifying:1,pairs_shown:1,nodes_qualifying:2,nodes_shown:2,awards_qualifying:4,awards_shown:4,value_qualifying:100,value_shown:100,truncated:false}};
const summary={min:1,p25:2,median:4,p75:8,p90:10,p99:12,max:12,mean:5,std:2,zeros:0,negative:0,n:10,iqr_outlier_rate:0,skew_ratio:2};
const featureKeys=["award_total_mdl","estimated_value_mdl","n_bidders","bid_window_days"];
const analyticsCatalog={features:featureKeys.map(key=>({key,label:key,group:"test",n:10,missing_rate:0,available:true,summary})),categories:[{key:"risk_level",label:"Risk band",n_levels:2},{key:"procedure",label:"Procedure",n_levels:1}],dates:{},min_pairs:2,n_rows:10};
function analyticalFixture(path:string,params:URLSearchParams):unknown {
 const groups=[{key:"high",label:"high",...summary,n:5},{key:"low",label:"low",...summary,n:5,p25:3,median:5,p75:9}];
 if(path.endsWith("/features"))return analyticsCatalog;
 if(path.endsWith("/correlations")){const columns=(params.get("features")??featureKeys.join(",")).split(",");return {columns,labels:columns,matrix:columns.map((_,i)=>columns.map((_,j)=>i===j?1:.5)),pairs:[{a:columns[0],b:columns[1],r:.5,abs_r:.5,direction:"positive",n:10}],n:10,method:"spearman",min_pairs:2};}
 if(path.endsWith("/distribution"))return {column:params.get("column"),label:params.get("column"),bins:[{x0:0,x1:4,mid:2,n:4},{x0:4,x1:8,mid:6,n:4},{x0:8,x1:12,mid:10,n:2}],ecdf:[[1,.1],[4,.5],[8,.8],[12,1]],summary,groups:groups.map(group=>({...group,share:.5})),group_by:null,log_x:false,scale:"linear"};
 if(path.endsWith("/scatter"))return {x:params.get("x"),y:params.get("y"),x_label:params.get("x"),y_label:params.get("y"),group:"risk_level",points:[{x:1,y:2,g:"high"},{x:2,y:3,g:"low"},{x:3,y:5,g:"high"}],fit:null,n:10,sampled:3};
 if(path.endsWith("/group-compare"))return {value:params.get("value"),value_label:params.get("value"),group:params.get("group"),group_label:params.get("group"),groups,n:10,dropped_groups:0};
 if(path.endsWith("/crosstab"))return {a:"procedure",b:"risk_level",a_label:"Procedure",b_label:"Risk",value:null,rows:["open"],cols:["high","low"],matrix:[[5,5]],max:5,dropped:0};
 return null;
}
export async function fixtureApi(page:Page) {
 await page.addInitScript(()=>{localStorage.setItem("mtender_lang","en");localStorage.setItem("mtender-theme","light");});
 await page.route("**/api/**",async route=>{
  const path=new URL(route.request().url()).pathname;
  expect(route.request().method(),"base fixture is read-only").toBe("GET");
  const data=path.startsWith("/api/analytics/")?analyticalFixture(path,new URL(route.request().url()).searchParams):path==="/api/stats"?stats:path==="/api/tenders"?{items:[tender],total:81}:path.endsWith("/model-analysis")?analysis:path.endsWith("/explanation")?explanation:path.startsWith("/api/tenders/")?tender:path==="/api/graph"?graph:path==="/api/meta"?{source:"test",n_tenders:2,scored:1,feature_columns:[],indicator_columns:[],unavailable:{},risk_bands:{},model:"test"}:path==="/api/health"?{ok:true,mongodb:{connected:false,error:"isolated test"}}:null;
  if(data===null) return route.fulfill({status:503,json:{detail:"Isolated test: advisory unavailable"}});
  await route.fulfill({json:data});
 });
}
export async function workspaceStore(page:Page) {
 const cases:any[]=[];const annotations:any[]=[];const watchlists:any[]=[];const items:any[]=[];const views:any[]=[];const activity:any[]=[];let seq=0;
 const state={cases,annotations,watchlists,items,views,activity,mutations:[] as string[],failNext:"",delay:0};
 const vocab={case_status:["open","closed"],case_priority:["low","medium","high","critical"],annotation_category:["observation"],watchlist_colors:{navy:"#123456",gold:"#987654"}};
 await page.route("**/api/workspace/**",async route=>{
  const req=route.request();const path=new URL(req.url()).pathname.replace("/api/workspace/","");const method=req.method();const parts=path.split("/");const entity=parts[0];const key=Number(parts[1]);
  const now="2026-01-01T00:00:00Z";
  const respond=(json:unknown,status=200)=>route.fulfill({status,json});
  if(method!=="GET") {state.mutations.push(method+" "+path);if(state.delay)await new Promise(resolve=>setTimeout(resolve,state.delay));if(state.failNext===method+" "+path){state.failNext="";return respond({detail:"TEST refusal: retry allowed"},500);} }
  if(path==="summary")return respond({counts:{cases:cases.length,annotations:annotations.length,watchlists:watchlists.length,watchlist_items:items.length,saved_views:views.length},cases_by_status:{},revision:seq,db_path:"test-only",vocab});
  if(entity==="activity")return respond({items:activity});
  if(entity==="watchlists"&&parts[1]==="items") {const row=items.find(x=>x.id===Number(parts[2]));if(method==="PATCH")Object.assign(row,req.postDataJSON());else if(method==="DELETE")items.splice(items.indexOf(row),1);activity.push({id:++seq,at:now,entity:"watchlist",action:"update",detail:"item"});return respond({updated:1,deleted:1});}
  const collection=({cases,annotations,watchlists,views} as Record<string,any[]>)[entity];if(!collection)return respond({detail:"fixture route missing"},404);
  const row=collection.find(x=>x.id===key);
  if(method==="GET"){
   if(!parts[1])return respond({items:collection.map(x=>entity==="watchlists"?{...x,n_items:items.filter(i=>i.watchlist_id===x.id).length}:x),vocab,colors:vocab.watchlist_colors});
   if(!row)return respond({detail:"not found"},404);
   if(entity==="cases")return respond({case:row,ocids:JSON.parse(row.ocids),annotations:annotations.filter(x=>x.case_id===key)});
   if(entity==="watchlists")return respond({watchlist:row,items:items.filter(x=>x.watchlist_id===key)});
  }
  const body=method==="DELETE"?{}:req.postDataJSON();
  if(method==="POST"&&parts[2]==="items") {const added=body.ocids.split(/[\n,]/).filter(Boolean).map((ocid:string)=>({id:++seq,watchlist_id:key,ocid,note:body.note,added_at:now}));items.push(...added);activity.push({id:++seq,at:now,entity:"watchlist",action:"add items",detail:"test"});return respond({added:added.length,items:items.filter(x=>x.watchlist_id===key)});}
  if(method==="POST") {
   const entry={id:++seq,ref:"TEST-"+seq,status:"open",priority:"medium",owner:"",summary:"",color:"navy",description:"",note:"",case_id:null,case_ref:null,case_title:null,created_at:now,updated_at:now,...body};
   if(entity==="cases")entry.ocids=JSON.stringify(body.ocids?body.ocids.split(/[\n,]/).filter(Boolean):[]);
   if(entity==="views")entry.payload=JSON.stringify(body.payload??{});
   collection.push(entry);activity.push({id:++seq,at:now,entity,action:"create",detail:entry.title??entry.name??entry.note});return respond(entry);
  }
  if(!row)return respond({detail:"not found"},404);
  if(method==="PATCH") {Object.assign(row,body);if(entity==="views"&&body.payload)row.payload=JSON.stringify(body.payload);if(entity==="cases"&&body.ocids!==undefined)row.ocids=JSON.stringify(body.ocids.split(/[\n,]/).filter(Boolean));}
  if(method==="DELETE")collection.splice(collection.indexOf(row),1);
  activity.push({id:++seq,at:now,entity,action:method==="DELETE"?"delete":"update",detail:"test"});return respond(method==="DELETE"?{deleted:1}:row);
 });
 return state;
}
