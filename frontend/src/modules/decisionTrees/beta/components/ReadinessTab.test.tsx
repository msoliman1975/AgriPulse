// Readiness tab (D15): a tenant sees each block, what it lacks and where to
// fix it; a platform admin sees counts per tenant and no block.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ar from "@/i18n/locales/ar/decisionTreesBeta.json";
import en from "@/i18n/locales/en/decisionTreesBeta.json";
import { setupTestI18n } from "@/i18n/testing";

import {
  READINESS_KINDS,
  READINESS_STATUSES,
  readinessFixPath,
  type TreeReadiness,
  type TreeReadinessSummary,
} from "../lib/readinessApi";
import { ReadinessTab } from "./ReadinessTab";

const get = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", () => ({ apiClient: { get } }));

const TENANT: TreeReadiness = {
  tree_id: "t1",
  tree_code: "date_palm_medjool_rpw_risk",
  version_id: "v1",
  readiness_note_en: "Record trap catches weekly.",
  readiness_note_ar: "سجّل صيد المصائد أسبوعياً.",
  requirements: [
    { kind: "crop_attribute", key: "palm_phase" },
    { kind: "signal", key: "date_rpw_trap_catch_value" },
  ],
  blocks_targeted: 2,
  blocks_assessed: 2,
  counts: { ready: 1, partial: 1, not_ready: 0 },
  blocks: [
    {
      block_id: "b1",
      block_code: "M-01",
      block_name: "Block one",
      block_name_ar: null,
      farm_id: "f1",
      farm_name: "QA farm",
      farm_name_ar: null,
      status: "partial",
      met: 1,
      total: 2,
      missing: [{ kind: "signal", key: "date_rpw_trap_catch_value" }],
    },
    {
      block_id: "b2",
      block_code: "M-02",
      block_name: "Block two",
      block_name_ar: null,
      farm_id: "f1",
      farm_name: "QA farm",
      farm_name_ar: null,
      status: "ready",
      met: 2,
      total: 2,
      missing: [],
    },
  ],
};

const SUMMARY: TreeReadinessSummary = {
  tree_id: "t1",
  readiness_note_en: null,
  readiness_note_ar: null,
  requirements: TENANT.requirements,
  tenants: [
    {
      tenant_id: "x",
      tenant_name: "QA Medjool",
      blocks_targeted: 34,
      counts: { ready: 0, partial: 30, not_ready: 4 },
      error: null,
    },
  ],
};

function wrap(node: ReactNode): ReactNode {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("ReadinessTab", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    get.mockReset();
    get.mockImplementation((url: string) =>
      Promise.resolve({ data: url.endsWith("/readiness-summary") ? SUMMARY : TENANT }),
    );
  });

  it("shows a tenant each block, what it lacks and the fix link", async () => {
    render(wrap(<ReadinessTab treeId="t1" scope="tenant" canFix />));
    expect(await screen.findByText("Record trap catches weekly.")).toBeInTheDocument();
    expect(screen.getByText("Block one")).toBeInTheDocument();
    expect(screen.getByText("Block two")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open block" });
    // The link carries the way back to this tab.
    expect(link).toHaveAttribute("href", "/farms/f1/blocks/b1?returnTo=%2F%3Ftab%3Dreadiness");
    expect(get).toHaveBeenCalledWith("/v1/platform/decision-trees/beta/t1/readiness");
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("hides fix links from someone who cannot edit blocks", async () => {
    render(wrap(<ReadinessTab treeId="t1" scope="tenant" canFix={false} />));
    expect(await screen.findByText("Block one")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows a platform admin counts per tenant and no block", async () => {
    render(wrap(<ReadinessTab treeId="t1" scope="platform" canFix={false} />));
    expect(await screen.findByText("QA Medjool")).toBeInTheDocument();
    expect(screen.getByText("Partial: 30")).toBeInTheDocument();
    expect(screen.queryByText("Block one")).toBeNull();
    expect(get).toHaveBeenCalledWith("/v1/platform/decision-trees/beta/t1/readiness-summary");
    expect(get).toHaveBeenCalledTimes(1);
  });
});

describe("readiness copy", () => {
  it.each([
    ["en", en],
    ["ar", ar],
  ] as const)("%s has every status, kind and fix label", (_lang, bundle) => {
    const r = bundle.readiness as unknown as Record<string, Record<string, string>>;
    for (const s of READINESS_STATUSES) expect(r.status[s]).toBeTruthy();
    for (const k of READINESS_KINDS) {
      expect(r.kind[k]).toBeTruthy();
      expect(r.fix[k]).toBeTruthy();
    }
    expect(Object.keys(en.readiness).sort()).toEqual(Object.keys(ar.readiness).sort());
  });
});

// Each fix link has to land on a page that can actually set the missing item.
describe("readinessFixPath", () => {
  const block = TENANT.blocks[0];
  const back = "/decision-trees-beta/x?tab=readiness";
  const q = `?returnTo=${encodeURIComponent(back)}`;

  it.each(["soil_texture", "salinity_class"])("sends %s to the block edit form", (key) => {
    expect(readinessFixPath(block, { kind: "block_field", key }, back)).toBe(
      `/farms/f1/blocks/b1/edit${q}`,
    );
  });

  it("sends growth stage, crop fields and heat units to the crop settings", () => {
    for (const req of [
      { kind: "block_field" as const, key: "growth_stage" },
      { kind: "crop_attribute" as const, key: "palm_phase" },
      { kind: "heat_units" as const, key: "total" },
    ]) {
      expect(readinessFixPath(block, req, back)).toBe(`/farms/f1/blocks/b1${q}#crop-settings`);
    }
  });

  it("links nowhere for a crop reference value, which the block cannot set", () => {
    expect(readinessFixPath(block, { kind: "reference", key: "kc_mid" }, back)).toBeNull();
  });

  it("links nowhere without a farm", () => {
    expect(readinessFixPath({ ...block, farm_id: null }, { kind: "signal", key: "x" })).toBeNull();
  });
});

describe("ReadinessTab reference values", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    get.mockReset();
    get.mockResolvedValue({
      data: {
        ...TENANT,
        blocks: [{ ...TENANT.blocks[0], missing: [{ kind: "reference", key: "kc_mid" }] }],
      },
    });
  });

  it("says where a reference value is set instead of linking to the block", async () => {
    render(wrap(<ReadinessTab treeId="t1" scope="tenant" canFix />));
    expect(await screen.findByText("Set in the crop catalogue (platform)")).toBeInTheDocument();
    expect(screen.getByText(/Crop reference value/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
