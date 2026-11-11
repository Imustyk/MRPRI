import {test,expect} from "@playwright/test";
import {ROUTES,WIDTHS,SHOTS,expectNoDocumentOverflow,expectTablesScrollInPlace} from "./helpers";
test("LIVE read-only route inventory, terminal states, unknown procedure vs route",async({page,request})=>{
 const writes:string[]=[];const errors:string[]=[];page.on("pageerror",error=>errors.push(error.message));
 await page.route("**/api/**",route=>{if(route.request().method()!=="GET"){writes.push(route.request().url());return route.abort();}return route.continue();});
 const res=await request.get("/api/tenders?limit=1");expect(res.ok()).toBe(true);const id=(await res.json()).items[0].tender_id;
 const coverage:unknown[]=[];
 for(const route of [...ROUTES,`/tenders/${encodeURIComponent(id)}`,"/tenders/unknown-test-readonly","/unknown-test-route"]){await page.goto(route);await expect(page.locator("h1")).toBeVisible();await page.waitForLoadState("networkidle");await expect(page.locator(".skeleton")).toHaveCount(0);for(const width of WIDTHS){await page.setViewportSize({width,height:900});await expectNoDocumentOverflow(page);await expectTablesScrollInPlace(page);}coverage.push({route,title:await page.locator("h1").innerText(),errors:await page.getByRole("alert").allInnerTexts()});if(["/","/tenders","/distributions","/network"].includes(route))await page.screenshot({path:`${SHOTS}/live${route.replace(/\W+/g,"-")}-terminal.png`,fullPage:true});}
 expect(writes).toEqual([]);expect(errors).toEqual([]);
 await test.info().attach("live-readonly-coverage",{body:JSON.stringify(coverage,null,2),contentType:"application/json"});
});
