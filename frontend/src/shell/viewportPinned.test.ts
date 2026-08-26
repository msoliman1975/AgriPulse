// Which routes the shell pins to the viewport.
//
// A source-level check, and it earns its place: this is the rule that was
// missed when the Farm Timeline shipped, and nothing else could have
// caught it. The map renders, the rail renders, every component test
// passes — and on prod the map grew to 15983px tall inside a 950px
// viewport, because the shell was only `min-h-screen` on that path and a
// bleed page's `h-full` had nothing to resolve against.
//
// It reads the file rather than rendering AppShell because the defect is
// "someone added a full-bleed map route and did not add it here", which is
// a fact about the source, not about a render.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// Resolved from the project root rather than from `import.meta.url`: under
// the jsdom environment that URL is not a file: URL, and fileURLToPath
// throws "The URL must be of scheme file" before a single test collects.
const root = process.cwd();
const APP_SHELL = readFileSync(resolve(root, "src/shell/AppShell.tsx"), "utf8");
const APP = readFileSync(resolve(root, "src/App.tsx"), "utf8");

/** Every path prefix AppShell pins to the viewport. */
function pinnedPrefixes(): string[] {
  const decl = /const viewportPinned =([\s\S]*?);/.exec(APP_SHELL);
  expect(decl, "viewportPinned declaration not found in AppShell.tsx").toBeTruthy();
  return [...decl![1].matchAll(/startsWith\("([^"]+)"\)/g)].map((m) => m[1]);
}

describe("viewport pinning", () => {
  it("pins the two map consoles and the timeline", () => {
    const prefixes = pinnedPrefixes();
    expect(prefixes).toContain("/labs/map");
    expect(prefixes).toContain("/timeline");
  });

  it("every full-bleed route is pinned", () => {
    // `<Page width="bleed">` means the page owns its own scrolling and
    // assumes a bounded height. A bleed page on an unpinned route is the
    // exact shape of the Timeline bug, so the two lists have to agree.
    //
    // Deliberately narrow: only routes this repo actually declares as
    // bleed, resolved from App.tsx's route table by page component name.
    const prefixes = pinnedPrefixes();
    const bleedPages = [
      "FarmConsolePage",
      "FarmConsoleV2Page",
      "MapExperiencePage",
      "FarmTimelinePage",
    ];
    const missing: string[] = [];
    for (const page of bleedPages) {
      const routes = [
        ...APP.matchAll(new RegExp(`path="([^"]+)"[^>]*element=\\{<${page}`, "g")),
      ].map((m) => m[1]);
      expect(routes.length, `no route found for ${page}`).toBeGreaterThan(0);
      for (const route of routes) {
        if (!prefixes.some((p) => route.startsWith(p))) missing.push(`${page} -> ${route}`);
      }
    }
    expect(missing).toEqual([]);
  });
});
