import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { WeatherTrendsCard } from "./WeatherTrendsCard";

// Weather indices are on incompatible scales, so the card must never put two
// of them on one axis in real units. These tests pin that contract: real
// units are shown one-per-facet, and the only shared-axis view is the
// unitless z-score.

const CATALOG = [
  { code: "temperature", name_en: "Temperature", name_ar: null, unit: "°C", sort_order: 1 },
  { code: "rainfall", name_en: "Rainfall", name_ar: null, unit: "mm", sort_order: 2 },
  { code: "radiation", name_en: "Radiation", name_ar: null, unit: "W/m²", sort_order: 3 },
].map((c) => ({
  ...c,
  description_en: null,
  description_ar: null,
  value_min: null,
  value_max: null,
  source_kind: "derived",
  default_visible: true,
  relation_indices_en: null,
  relation_indices_ar: null,
  relation_disease_en: null,
  relation_disease_ar: null,
  relation_insect_en: null,
  relation_insect_ar: null,
}));

const h = vi.hoisted(() => ({ timeseries: vi.fn() }));

vi.mock("@/api/weatherIndices", async () => {
  const actual =
    await vi.importActual<typeof import("@/api/weatherIndices")>("@/api/weatherIndices");
  return { ...actual, getWeatherIndexCatalog: vi.fn(), getWeatherIndexTimeseries: h.timeseries };
});

async function renderCard() {
  const { getWeatherIndexCatalog } = await import("@/api/weatherIndices");
  vi.mocked(getWeatherIndexCatalog).mockResolvedValue(CATALOG);
  h.timeseries.mockImplementation((_farm: string, code: string) =>
    Promise.resolve({
      farm_id: "f1",
      index_code: code,
      points: [
        { date: "2026-05-01", value: "20", zscore: "-1.5", baseline_mean: "22", baseline_std: "2" },
        { date: "2026-05-02", value: "25", zscore: "1.5", baseline_mean: "22", baseline_std: "2" },
      ],
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <WeatherTrendsCard farmId="f1" />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByText("Temperature")).toBeTruthy());
  return view;
}

describe("WeatherTrendsCard", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
  });

  it("defaults to per-index facets, each labelled with its own unit", async () => {
    await renderCard();
    // One row per index, each carrying its real unit — no shared axis.
    for (const [name, unit] of [
      ["Temperature", "°C"],
      ["Rainfall", "mm"],
      ["Radiation", "W/m²"],
    ]) {
      expect(screen.getByText(name)).toBeTruthy();
      expect(screen.getByText(unit)).toBeTruthy();
    }
    expect(screen.getByText(/not comparable between rows/i)).toBeTruthy();
  });

  it("switches to a single shared axis only in unitless z-scores", async () => {
    const user = userEvent.setup();
    await renderCard();

    await user.click(screen.getByRole("radio", { name: "Compare" }));

    expect(screen.getByText(/z-score against its seasonal normal/i)).toBeTruthy();
    // Units must NOT be presented once everything shares one axis.
    expect(screen.queryByText("°C")).toBeNull();
    expect(screen.queryByText("W/m²")).toBeNull();
  });

  it("keeps a legend so series identity is never colour-alone", async () => {
    const user = userEvent.setup();
    const { container } = await renderCard();
    await user.click(screen.getByRole("radio", { name: "Compare" }));

    const swatches = container.querySelectorAll('span[aria-hidden="true"]');
    expect(swatches.length).toBe(CATALOG.length);
    for (const c of CATALOG) expect(screen.getByText(c.name_en)).toBeTruthy();
  });

  it("requests every index over the selected span", async () => {
    const user = userEvent.setup();
    await renderCard();
    h.timeseries.mockClear();

    await user.click(screen.getByRole("radio", { name: "7d" }));

    await waitFor(() => expect(h.timeseries).toHaveBeenCalledTimes(CATALOG.length));
    const codes = h.timeseries.mock.calls.map((c) => c[1] as string);
    expect(new Set(codes)).toEqual(new Set(CATALOG.map((c) => c.code)));
  });

  it("says so when a farm has no weather history yet", async () => {
    const { getWeatherIndexCatalog } = await import("@/api/weatherIndices");
    vi.mocked(getWeatherIndexCatalog).mockResolvedValue(CATALOG);
    h.timeseries.mockResolvedValue({ farm_id: "f1", index_code: "temperature", points: [] });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <WeatherTrendsCard farmId="f1" />
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(screen.getByText(/No weather index data for this period/i)).toBeTruthy(),
    );
  });
});

// Guard against the whole point of the card being undone later: recharts
// renders one <YAxis> per axis, so a units view with a single shared axis
// would mean somebody collapsed the facets.
describe("WeatherTrendsCard scale contract", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
  });

  it("renders one chart per index in units mode", async () => {
    const { container } = await renderCard();
    const charts = container.querySelectorAll(".recharts-responsive-container");
    expect(charts.length).toBe(CATALOG.length);
  });

  it("renders exactly one chart in compare mode", async () => {
    const user = userEvent.setup();
    const { container } = await renderCard();
    await user.click(screen.getByRole("radio", { name: "Compare" }));
    await waitFor(() =>
      expect(container.querySelectorAll(".recharts-responsive-container").length).toBe(1),
    );
  });
});
