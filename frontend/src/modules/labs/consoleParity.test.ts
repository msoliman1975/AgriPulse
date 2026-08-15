import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Two Farm Consoles ship side by side: the default at /labs/map (mapnext,
// FarmConsolePage) and the beta at /labs/map-v2 (console, FarmConsoleV2Page).
// The side nav lists BOTH under the same "Farm management" label, so whichever
// one an operator clicks is the whole product to them.
//
// Farm-level imagery and weather subscriptions shipped into v2's settings
// drawer only. The default console's drawer rendered just the farm-edit form,
// so for every operator who clicked the first row there was no way to
// subscribe a farm to imagery or weather at all — and nothing failed, nothing
// logged, the control simply was not there.
//
// This is a source-level check on purpose. Rendering either console needs the
// map, the query client and a dozen loaders; the defect it guards is not a
// rendering bug but a "someone added it to one file and not the other" bug,
// which is exactly what reading both files catches. Delete this at cutover,
// when one console is gone.

function read(relative: string): string {
  return readFileSync(fileURLToPath(new URL(relative, import.meta.url)), "utf8");
}

const CONSOLES: { label: string; source: string }[] = [
  { label: "default console (/labs/map)", source: read("./mapnext/FarmConsolePage.tsx") },
  { label: "v2 console (/labs/map-v2)", source: read("./console/SettingsDrawer.tsx") },
];

describe("both Farm Consoles expose farm-level configuration", () => {
  it.each(CONSOLES)("$label mounts FarmSubscriptionsPanel", ({ source }) => {
    expect(source).toContain("<FarmSubscriptionsPanel");
    expect(source).toContain("FarmSubscriptionsPanel }");
  });
});
