import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The scout app. Port 5174 so it can run alongside the web frontend (5173)
// during development — a supervisor dispatching on the web and a scout
// receiving on the phone is the loop being developed, and you want both open.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    // Same trick as the web app: proxy /api so dev needs no CORS. On a real
    // device Capacitor serves from a different origin, so the built app talks
    // to VITE_API_BASE_URL directly and the backend must allow that origin.
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: true },
});
