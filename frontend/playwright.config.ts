import { defineConfig, devices } from "@playwright/test";

/**
 * Route × width × language × theme checks run against the real dev server with
 * the real API (vite proxies /api to 127.0.0.1:8000 — start the backend first:
 *   uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
 * from the repository root). Screenshots land in docs/frontend-verification/.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Tap must work like a click for the touch-equivalence checks.
    hasTouch: true,
  },
  projects: [
    {
      name: "chromium",
      // Tap must work like a click for the touch-equivalence checks.
      use: { ...devices["Desktop Chrome"], hasTouch: true },
    },
  ],
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 5173",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
