import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/** Unit/component tests (jsdom). Browser-level checks live in e2e/ (Playwright). */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    // i18n is a module singleton shared across tests in one file.
    sequence: { concurrent: false },
  },
});
