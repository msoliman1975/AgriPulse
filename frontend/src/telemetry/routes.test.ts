import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";
import type { RouteObject } from "react-router-dom";

import { ROUTE_MANIFEST, matchRouteInfo, routeTemplate } from "./routes";

/**
 * The manifest duplicates App.tsx, so it needs a test that fails when they
 * diverge — otherwise a new page silently reports as `unknown` and disappears
 * from every chart, which is the worst kind of telemetry bug: invisible, and
 * it looks like "nobody uses that page".
 */

// vitest runs with jsdom, where `import.meta.url` is an http: URL and
// fileURLToPath rejects it. cwd is the frontend package root.
const APP_TSX = resolve(process.cwd(), "src/App.tsx");

function pathsInAppTsx(): Set<string> {
  const source = readFileSync(APP_TSX, "utf-8");
  const found = new Set<string>();
  for (const match of source.matchAll(/path="([^"]+)"/g)) {
    found.add(match[1]);
  }
  return found;
}

function pathsInManifest(routes: RouteObject[] = ROUTE_MANIFEST): Set<string> {
  const found = new Set<string>();
  const walk = (list: RouteObject[]): void => {
    for (const route of list) {
      if (route.path) found.add(route.path);
      if (route.children) walk(route.children);
    }
  };
  walk(routes);
  return found;
}

describe("ROUTE_MANIFEST", () => {
  it("covers every route declared in App.tsx", () => {
    const missing = [...pathsInAppTsx()].filter((p) => !pathsInManifest().has(p)).sort();
    expect(
      missing,
      "Add these to ROUTE_MANIFEST in src/telemetry/routes.ts, or their page " +
        "will report route=unknown and vanish from the usage dashboard.",
    ).toEqual([]);
  });

  it("declares no route App.tsx does not have", () => {
    const appPaths = pathsInAppTsx();
    const stale = [...pathsInManifest()].filter((p) => !appPaths.has(p)).sort();
    expect(stale, "Remove these from ROUTE_MANIFEST — App.tsx no longer has them.").toEqual([]);
  });
});

describe("routeTemplate", () => {
  it("returns the template, never the resolved path", () => {
    expect(routeTemplate("/insights/8f3a1b2c-0000-4000-8000-000000000000")).toBe(
      "/insights/:farmId",
    );
  });

  it("joins nested layout segments", () => {
    expect(routeTemplate("/settings/integrations/health")).toBe("/settings/integrations/health");
  });

  it("resolves a bare layout path", () => {
    expect(routeTemplate("/farms")).toBe("/farms");
  });

  it("reports an unmatched path as unknown rather than inventing one", () => {
    // The catch-all `*` route matches everything; reporting it as a template
    // would put every 404 into one bucket named "*".
    expect(routeTemplate("/no/such/page/anywhere")).toBe("unknown");
  });

  it("extracts farmId from the match, not from a hook", () => {
    const info = matchRouteInfo("/board/8f3a1b2c-0000-4000-8000-000000000000");
    expect(info.template).toBe("/board/:farmId");
    expect(info.farmId).toBe("8f3a1b2c-0000-4000-8000-000000000000");
  });

  it("leaves farmId undefined on a route without one", () => {
    expect(matchRouteInfo("/decision-trees").farmId).toBeUndefined();
  });
});
