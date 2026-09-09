import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build identity, stamped onto every telemetry event as `app_version`.
// Without it a behaviour change cannot be attributed to a deploy: "errors on
// /reports tripled on Tuesday" is only actionable once you know which build
// Tuesday was running.
//
// SEVEN characters, deliberately: that is exactly the GHCR tag the cluster
// runs, so `app_version` can be compared to a deployed image by eye and by
// equality. Twelve was the original length and it matched nothing.
//
// The first production build of this recorded "dev" for every event. The
// value came from GITHUB_SHA or a local `git rev-parse`, and inside the
// frontend image build there is neither: the Dockerfile copies source, not
// `.git`, and container builds do not inherit workflow env. So the column was
// populated with a useless constant. The image now takes APP_VERSION as a
// build arg and exposes it as APP_VERSION, which is why that is read first —
// it is the only one of the three that is true in the image. The name has no
// VITE_ prefix on purpose: that would also inline it into `import.meta.env`,
// untruncated, giving the bundle a second copy that disagrees with this one.
function buildVersion(): string {
  const provided = process.env.APP_VERSION ?? process.env.GITHUB_SHA;
  if (provided) return provided.slice(0, 7);
  try {
    return execSync("git rev-parse --short=7 HEAD", { encoding: "utf-8" }).trim();
  } catch {
    // A tarball with no .git, which is the local-dev case. Never a released
    // image: the build arg is always set by CI.
    return "dev";
  }
}

// AgriPulse dev server.
// 5173 matches the Keycloak realm's redirectUris (infra/dev/compose.yaml)
// and the backend's CORS_ALLOWED_ORIGINS default.
export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(buildVersion()),
  },
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
      // Overridable because several worktrees run side by side: without it
      // the dev server silently proxies to whichever backend happens to hold
      // :8000, which is how a new route reads as a 404 in a tree that has it.
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
        // A remote target is routed by Host at the ingress, so the header has
        // to be rewritten; a local backend does not care and the original
        // Host is more useful in its logs.
        changeOrigin: (process.env.VITE_API_TARGET ?? "").startsWith("https://"),
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
