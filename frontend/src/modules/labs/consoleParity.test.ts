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
  // One shared component, mounted twice. Asserting on the SHARED tab rather
  // than on each panel is what makes the guard hold as panels come and go:
  // add a section to FarmSettingsTab and both consoles get it by construction.
  it.each(CONSOLES)("$label mounts the shared FarmSettingsTab", ({ source }) => {
    expect(source).toContain("<FarmSettingsTab");
    expect(source).toContain("FarmSettingsTab }");
  });

  it.each(CONSOLES)("$label does not re-inline its own farm form", ({ source }) => {
    // A transcribed copy is exactly how subscriptions and cell size went
    // missing from one console; the copy drifted and nothing failed.
    expect(source).not.toContain("function FarmEditTab");
  });
});

describe("the shared farm tab carries every farm-level setting", () => {
  const tab = read("./mapnext/FarmSettingsTab.tsx");

  it("groups details, subscriptions and zones in that order", () => {
    const details = tab.indexOf("settingsFarm.detailsTitle");
    const subs = tab.indexOf("<FarmSubscriptionsPanel");
    const zones = tab.indexOf("<FarmZonesPanel");
    expect(details).toBeGreaterThan(-1);
    expect(subs).toBeGreaterThan(details);
    expect(zones).toBeGreaterThan(subs);
  });

  it("puts the save and danger-zone actions after every settings group", () => {
    // The ask was explicit: groups first, then Save and Inactivate.
    expect(tab.indexOf("dangerZone.title")).toBeGreaterThan(tab.indexOf("<FarmZonesPanel"));
    expect(tab.indexOf("settingsFarm.saveDetails")).toBeGreaterThan(tab.indexOf("<FarmZonesPanel"));
  });

  it("scopes the save button to the details form only", () => {
    // It sits below three sections that save on change. Submitting via the
    // form id keeps it bound to the fields it can actually save, and the
    // label names that scope rather than saying a bare "Save".
    expect(tab).toContain("form={DETAILS_FORM_ID}");
    expect(tab).toContain("settingsFarm.saveDetails");
  });
});
