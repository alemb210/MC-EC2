import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, Vite serves the UI on :3000 and forwards API calls, so the browser only
// ever talks to one origin (no CORS). In prod, FastAPI serves dist/ itself.
const targets: Record<string, string> = {
  development: "http://127.0.0.1:8000",
  live: "https://k19j61rb5c.execute-api.us-east-1.amazonaws.com",
};

export default defineConfig(({ mode }) => {
  const proxy = { target: targets[mode] ?? targets.development, changeOrigin: true };
  return {
    plugins: [react()],
    // Cognito only allows http://localhost:3000/ as the callback URL, so fail
    // instead of silently moving to another port.
    server: { port: 3000, strictPort: true, proxy: { "/health": proxy, "/servers": proxy } },
  };
});
