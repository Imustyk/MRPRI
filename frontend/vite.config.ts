import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Override with VITE_API_TARGET when the backend runs on another port,
      // e.g. VITE_API_TARGET=http://127.0.0.1:8099 npm run dev
      "/api": process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
    },
  },
});
