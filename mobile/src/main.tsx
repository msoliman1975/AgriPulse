import { Capacitor } from "@capacitor/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import "./styles.css";

// Marks the document when this is the Android app rather than a browser tab.
// From targetSdk 35 Android draws the app edge to edge, so the WebView starts
// behind the status bar; the stylesheet uses this to guarantee a minimum top
// inset even on a WebView that reports `env(safe-area-inset-top)` as zero.
if (Capacitor.isNativePlatform()) {
  document.documentElement.classList.add("native");
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
