import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./i18n";
import { App } from "./App";
import "./styles/index.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Mount point #root missing from index.html");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
