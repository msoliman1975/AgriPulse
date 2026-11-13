// Inputs catalogue (D20): doses and organic status, the platform/tenant
// split, and the EN/AR copy.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  INPUT_CATEGORIES,
  INPUT_METHODS,
  ORGANIC_STATUSES,
  formatDose,
  type Input,
} from "@/api/inputs";
import ar from "@/i18n/locales/ar/inputs.json";
import en from "@/i18n/locales/en/inputs.json";
import { setupTestI18n } from "@/i18n/testing";

import { InputsCataloguePage } from "./InputsCataloguePage";

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn() }));
vi.mock("@/api/client", () => ({ apiClient: http }));
const can = vi.hoisted(() => ({ write: true }));
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => can.write }));

const base = {
  name_ar: null,
  active_ingredient: null,
  organic_list: null,
  phi_days: null,
  rei_hours: null,
  crop_paths: [],
  notes: null,
  is_active: true,
  created_at: "2026-11-13T00:00:00Z",
  updated_at: "2026-11-13T00:00:00Z",
};
const SULPHUR: Input = {
  ...base,
  id: "p1",
  scope: "platform",
  code: "sulphur",
  name_en: "Sulphur",
  category: "mineral_or_botanical_treatment",
  methods: ["dust"],
  organic_status: "unverified",
  doses: [
    {
      crop_path: "date_palm.medjool",
      value: null,
      value_min: "100",
      value_max: "150",
      unit: "g/plant",
      unit_note: null,
      context: "early July",
      reference: "Manual 1.7, 10.3 #5",
    },
  ],
};
const OURS: Input = {
  ...base,
  id: "t1",
  scope: "tenant",
  code: "our_compost",
  name_en: "Our compost",
  category: "organic_fertiliser",
  methods: ["basin"],
  organic_status: "permitted",
  doses: [],
};

function wrap(node: ReactNode): ReactNode {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(async () => {
  await setupTestI18n("en");
  can.write = true;
  http.get.mockReset();
  http.get.mockImplementation((url: string) =>
    Promise.resolve({ data: url === "/v1/inputs" ? [SULPHUR, OURS] : [] }),
  );
});

describe("InputsCataloguePage", () => {
  it("lists doses, organic status and whose row it is", async () => {
    render(wrap(<InputsCataloguePage scope="tenant" />));
    const row = (await screen.findByText("Sulphur")).closest("tr")!;
    expect(within(row).getByText("100–150 g/plant")).toBeInTheDocument();
    expect(within(row).getByText("Unverified")).toBeInTheDocument();
    expect(within(row).getByText("Platform")).toBeInTheDocument();
    expect(
      within(screen.getByText("Our compost").closest("tr")!).getByText("Yours"),
    ).toBeInTheDocument();
  });

  it("lets a tenant edit only its own rows", async () => {
    render(wrap(<InputsCataloguePage scope="tenant" />));
    fireEvent.click(await screen.findByText("Sulphur"));
    expect(await screen.findByText("Manual 1.7, 10.3 #5", { exact: false })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByText("Our compost"));
    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("offers no writing without the capability", async () => {
    can.write = false;
    render(wrap(<InputsCataloguePage scope="platform" />));
    await screen.findByText("Sulphur");
    expect(screen.queryByRole("button", { name: "New input" })).toBeNull();
  });
});

describe("inputs copy", () => {
  it("formats doses", () => {
    expect(formatDose({ ...SULPHUR.doses[0] })).toBe("100–150 g/plant");
    expect(
      formatDose({
        ...SULPHUR.doses[0],
        value: "1",
        value_min: null,
        value_max: null,
        unit: "other",
        unit_note: "trap per 100 m",
      }),
    ).toBe("1 trap per 100 m");
  });

  it.each([
    ["en", en],
    ["ar", ar],
  ] as const)("%s labels every category, method and status", (_lang, bundle) => {
    const b = bundle as unknown as Record<string, Record<string, string>>;
    for (const c of INPUT_CATEGORIES) expect(b.categories[c]).toBeTruthy();
    for (const m of INPUT_METHODS) expect(b.methods[m]).toBeTruthy();
    for (const s of ORGANIC_STATUSES) expect(b.organic[s]).toBeTruthy();
  });
});
