import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { WeatherSection } from "./WeatherSection";

// The section replaced four sibling cards that each read weather at a
// different altitude. These tests pin what the consolidation must not lose:
// every index is still reachable, the scales stay honest, and the one-axis
// view stays inside the number of series a categorical palette can separate.

const CODES = [
  ["temperature", "Temperature", "°C"],
  ["rainfall", "Rainfall", "mm"],
  ["radiation", "Radiation", "W/m²"],
  ["wind", "Wind", "m/s, °"],
  ["evapotranspiration", "Evapotranspiration", "mm"],
  ["evaporation_coeff", "Dry-down", "mm"],
  ["rain_et_balance", "Rain vs ET", "mm"],
  ["humidity", "Humidity", "%"],
] as const;

const CATALOG = CODES.map(([code, name_en, unit], i) => ({
  code,
  name_en,
  name_ar: null,
  unit,
  sort_order: i + 1,
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

// Z-scores chosen so the compare cap has an unambiguous winner set:
// humidity (-3.1), wind (2.6), rainfall (-2.2), temperature (1.8).
const ZSCORE: Record<string, string> = {
  temperature: "1.8",
  rainfall: "-2.2",
  radiation: "0.2",
  wind: "2.6",
  evapotranspiration: "0.4",
  evaporation_coeff: "-0.1",
  rain_et_balance: "0.3",
  humidity: "-3.1",
};

const h = vi.hoisted(() => ({ timeseries: vi.fn(), summary: vi.fn(), catalog: vi.fn() }));

vi.mock("@/api/weatherIndices", async () => {
  const actual =
    await vi.importActual<typeof import("@/api/weatherIndices")>("@/api/weatherIndices");
  return {
    ...actual,
    getWeatherIndexCatalog: h.catalog,
    getWeatherIndexSummary: h.summary,
    getWeatherIndexTimeseries: h.timeseries,
  };
});

vi.mock("@/api/blocks", () => ({
  listBlocks: vi.fn(() => Promise.resolve({ items: [{ id: "b1", name: "Block 1" }], total: 1 })),
}));

vi.mock("@/api/weather", () => ({
  getDerivedDaily: vi.fn(() => Promise.resolve([])),
  getForecast: vi.fn(() => Promise.resolve({ days: [] })),
}));

vi.mock("@/api/weatherRisk", () => ({
  getWeatherRiskSummary: vi.fn(() =>
    Promise.resolve({
      risks: [
        { block_id: "b1", risk_code: "powdery_mildew", level: "high", score: "80" },
        { block_id: "b2", risk_code: "anthracnose", level: "moderate", score: "50" },
      ],
    }),
  ),
}));

function renderSection(props: { showRisk?: boolean } = {}) {
  h.catalog.mockResolvedValue(CATALOG);
  h.summary.mockResolvedValue({
    farm_id: "f1",
    indices: CODES.map(([code]) => ({
      index_code: code,
      value: "20",
      zscore: ZSCORE[code],
      trend_7d_delta: "0.5",
      as_of: "2026-06-30",
    })),
  });
  h.timeseries.mockImplementation((_farm: string, code: string) =>
    Promise.resolve({
      farm_id: "f1",
      index_code: code,
      points: [
        {
          date: "2026-06-29",
          value: "20",
          zscore: ZSCORE[code],
          baseline_mean: "22",
          baseline_std: "2",
        },
        {
          date: "2026-06-30",
          value: "21",
          zscore: ZSCORE[code],
          baseline_mean: "22",
          baseline_std: "2",
        },
      ],
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <WeatherSection farmId="f1" showRisk={props.showRisk ?? true} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("WeatherSection", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    vi.clearAllMocks();
  });

  it("is one section, not four cards saying weather", async () => {
    const { container } = renderSection();
    await waitFor(() => expect(screen.getByText("Temperature")).toBeTruthy());

    expect(container.querySelectorAll("section").length).toBe(1);
    // One time-span control for the whole section — the four cards each had
    // their own, so a reader could leave them showing different windows.
    expect(screen.getAllByRole("radiogroup", { name: /time span/i }).length).toBe(1);
  });

  it("shows every catalogued index, humidity included", async () => {
    renderSection();
    await waitFor(() => expect(screen.getByText("Temperature")).toBeTruthy());

    const strip = screen.getByRole("group", { name: /weather indices/i });
    expect(within(strip).getAllByRole("button").length).toBe(CODES.length);
    // Humidity is the eighth index and the reason the palette had to grow;
    // it must be a card of its own, not a missing slot.
    expect(within(strip).getByText("Humidity")).toBeTruthy();
  });

  it("keeps real units one-per-facet and never on a shared axis", async () => {
    renderSection();
    await waitFor(() => expect(screen.getByText("Temperature")).toBeTruthy());

    // Units mode is the default: one chart per index, each labelled with its
    // own unit. Eight indices on eight scales.
    await waitFor(() =>
      expect(document.querySelectorAll(".recharts-responsive-container").length).toBeGreaterThan(1),
    );
    expect(screen.getByText(/not comparable between rows/i)).toBeTruthy();
  });

  it("caps the shared-axis view at four series and says which", async () => {
    const user = userEvent.setup();
    renderSection();
    await waitFor(() => expect(screen.getByText("Temperature")).toBeTruthy());

    await user.click(screen.getByRole("radio", { name: "Compare" }));

    // Eight lines on one axis is past what any categorical palette can keep
    // separable, so compare charts only the four furthest from normal.
    expect(await screen.findByText(/furthest from their seasonal normal/i)).toBeTruthy();
    await waitFor(() =>
      expect(document.querySelectorAll('li > span[aria-hidden="true"]').length).toBe(4),
    );
    // Ranked by |z|: humidity -3.1, wind 2.6, rainfall -2.2, temperature 1.8.
    // Radiation (z 0.2) is nowhere near the top four, so it is not in the
    // legend — which is also the only place the cap is visible to a reader.
    const legend = document.querySelectorAll("li > span[aria-hidden='true']");
    const legendText = [...legend].map((s) => s.parentElement?.textContent ?? "").join(" ");
    for (const name of ["Humidity", "Wind", "Rainfall", "Temperature"]) {
      expect(legendText).toContain(name);
    }
    expect(legendText).not.toContain("Radiation");
  });

  it("drills into a single index with its climatology band", async () => {
    const user = userEvent.setup();
    renderSection();
    await waitFor(() => expect(screen.getByText("Temperature")).toBeTruthy());

    const strip = screen.getByRole("group", { name: /weather indices/i });
    await user.click(within(strip).getByRole("button", { name: /Humidity/ }));

    // The band is the one thing neither all-index view can show, which is why
    // selection swaps the panel rather than adding a chart below it.
    expect(await screen.findByText(/Humidity — last 90 days/i)).toBeTruthy();
    expect(screen.getByText("Show all indices")).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "Compare" })).toBeNull();
  });

  it("closes with per-block risk, and drops it without the capability", async () => {
    renderSection({ showRisk: true });
    await waitFor(() => expect(screen.getByText("Disease & pest risk")).toBeTruthy());
    // Worst level per block: b1 high, b2 moderate — two blocks at risk.
    expect(await screen.findByText("2 blocks at risk")).toBeTruthy();

    screen.getByText("Disease & pest risk");
  });

  it("omits the risk row when the caller lacks weather_risk.read", async () => {
    renderSection({ showRisk: false });
    await waitFor(() => expect(screen.getByText("Temperature")).toBeTruthy());
    expect(screen.queryByText("Disease & pest risk")).toBeNull();
  });
});
