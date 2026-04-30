import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, type RenderResult } from "@testing-library/react";

import { PrefsProvider } from "@/prefs/PrefsContext";

export interface RouterRenderOptions {
  route?: string;
  path?: string;
}

/**
 * Renders an element inside a MemoryRouter at the given path so route
 * params resolve. Wraps in PrefsProvider so usePrefs hooks work.
 */
export function renderAtRoute(
  element: ReactElement,
  options: RouterRenderOptions = {},
): RenderResult {
  const { route = "/", path = "/*" } = options;
  return render(
    <PrefsProvider>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={element} />
        </Routes>
      </MemoryRouter>
    </PrefsProvider>,
  );
}
