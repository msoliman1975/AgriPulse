import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./i18n";
import { App } from "./App";
import { AppErrorBoundary } from "./components/ErrorBoundary";
import "./styles/index.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Mount point #root missing from index.html");
}

createRoot(rootElement).render(
  <StrictMode>
    {/* Outermost boundary. Catches anything that throws above the routes -
        the auth provider, the preferences provider, the router itself. It
        is mounted here rather than inside <App> so it also survives <App>
        failing to render at all. Its fallback uses no translation and no
        shell, because those are among the things that can be what broke.
        The per-page boundary lives in <AppShell>. */}
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
