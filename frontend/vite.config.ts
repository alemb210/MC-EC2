import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = "http://127.0.0.1:8000";

// In dev, Vite serves the UI on :5173 and forwards API calls to uvicorn.
// In prod, FastAPI serves dist/ itself, so no proxy is involved.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/health": backend,
      "/servers": backend,
      "/api": backend,
    },
  },
});
