// Reference values tab (D18/D23): inherited values say where from, spacing
// gives plants per hectare, and a curator can set a value on this path.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { formatReference } from "@/api/referenceValues";
import { setupTestI18n } from "@/i18n/testing";

import { ReferenceValuesPanel } from "./CatalogReferenceValues";

const http = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock("@/api/client", () => ({ apiClient: http }));

const KEYS = [
  { key: "soil_ece_threshold_ds_m", group: "salinity", unit: "dS/m", lower: 0, upper: 100 },
  { key: "yield_per_plant_kg", group: "yield", unit: "kg/plant", lower: 0, upper: 100000 },
  { key: "row_spacing_m", group: "spacing", unit: "m", lower: 0, upper: 1000 },
];
const VIEW = {
  crop_path: "date_palm.medjool",
  own: [
    {
      crop_path: "date_palm.medjool",
      key: "yield_per_plant_kg",
      value: null,
      value_min: "60",
      value_max: "72",
      note: "Manual 1.7, 3.1 #7",
    },
  ],
  resolved: {
    soil_ece_threshold_ds_m: {
      value: "4.0",
      value_min: null,
      value_max: null,
      note: null,
      from_path: "date_palm",
    },
    yield_per_plant_kg: {
      value: null,
      value_min: "60",
      value_max: "72",
      note: "Manual 1.7, 3.1 #7",
      from_path: "date_palm.medjool",
    },
  },
  plants_per_ha: 123.5,
};

function wrap(node: ReactNode): ReactNode {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

beforeEach(async () => {
  await setupTestI18n("en");
  http.get.mockReset();
  http.put.mockReset();
  http.get.mockImplementation((url: string) => {
    if (url === "/v1/reference-values/keys") return Promise.resolve({ data: KEYS });
    if (url.startsWith("/v1/reference-values/")) return Promise.resolve({ data: VIEW });
    if (url === "/v1/sources/links") return Promise.resolve({ data: [] });
    return Promise.reject(new Error(url));
  });
  http.put.mockResolvedValue({ data: VIEW });
});

describe("ReferenceValuesPanel", () => {
  it("shows inherited values with their origin and derived plants per hectare", async () => {
    render(wrap(<ReferenceValuesPanel cropPath="date_palm.medjool" canManage={false} />));
    const ece = (await screen.findByText("Soil salinity threshold (ECe)")).closest("li")!;
    expect(within(ece).getByText("4")).toBeInTheDocument();
    expect(within(ece).getByText("From date_palm")).toBeInTheDocument();
    const yieldRow = screen.getByText("Yield per plant").closest("li")!;
    expect(within(yieldRow).getByText("60–72")).toBeInTheDocument();
    expect(within(yieldRow).queryByText(/^From /)).toBeNull();
    expect(screen.getByText("123.5")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set here" })).toBeNull();
  });

  it("lets a curator set a value on this path", async () => {
    render(wrap(<ReferenceValuesPanel cropPath="date_palm.medjool" canManage />));
    const row = (await screen.findByText("Row spacing")).closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: "Set here" }));
    fireEvent.change(within(row).getByLabelText("Value"), { target: { value: "9" } });
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(http.put).toHaveBeenCalledWith(
        "/v1/admin/reference-values/date_palm.medjool/row_spacing_m",
        { value: 9, value_min: null, value_max: null, note: null },
      ),
    );
  });
});

describe("formatReference", () => {
  it("reads a value, a range, or both", () => {
    expect(formatReference({ value: "20", value_min: "18", value_max: "28" })).toBe("20 (18–28)");
    expect(formatReference({ value: null, value_min: "60", value_max: "72" })).toBe("60–72");
    expect(formatReference({ value: "4.0", value_min: null, value_max: null })).toBe("4");
  });
});
