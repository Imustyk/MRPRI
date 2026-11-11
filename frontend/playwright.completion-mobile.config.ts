import { defineConfig, devices } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig(base, { outputDir: "/tmp/mrpri-frontend-mobile-results", testMatch: "completion.spec.ts", grep: /Workspace|Saved views/, projects:[{name:"chromium-mobile", use:{...devices["Desktop Chrome"],viewport:{width:375,height:812},hasTouch:true}}] });
