import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// AgriPulse dev server.
// 5173 matches the Keycloak realm's redirectUris (infra/dev/compose.yaml)
// and the backend's CORS_ALLOWED_ORIGINS default.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      // Forward API calls to the natively-running FastAPI backend so we
      // do not need browser-side CORS during dev. Keycloak token + axios
      // baseURL stay relative.
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
