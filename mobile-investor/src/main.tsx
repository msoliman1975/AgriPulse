import { Capacitor } from "@capacitor/core";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import "./styles.css";

// Marks the Android build, so the stylesheet keeps a floor under the status
// bar when the WebView reports a zero safe-area inset.
if (Capacitor.isNativePlatform()) {
  document.documentElement.classList.add("native");
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
