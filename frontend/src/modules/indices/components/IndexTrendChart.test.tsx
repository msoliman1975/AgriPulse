import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setupTestI18n } from "@/i18n/testing";

const BLOCK_ID = "22222222-2222-2222-2222-222222222222";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));

// Recharts queries window dimensions; jsdom returns 0/0 by default and
// the ResponsiveContainer suppresses its children. Stub the inner
// container so the chart still renders measurable nodes for tests.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 600, height: 300 }} data-testid="chart-frame">
        {children}
      </div>
    ),
  };
});

const getTimeseriesMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/indices", async () => {
  const actual = await vi.importActual<object>("@/api/indices");
  return { ...actual, getTimeseries: getTimeseriesMock };
});

import { IndexTrendChart } from "./IndexTrendChart";

beforeEach(() => {
  getTimeseriesMock.mockReset();
});

describe("IndexTrendChart", () => {
  it("renders empty state in english", async () => {
    await setupTestI18n("en");
    getTimeseriesMock.mockResolvedValueOnce({
      block_id: BLOCK_ID,
      index_code: "ndvi",
      granularity: "daily",
      points: [],
    });
    render(<IndexTrendChart blockId={BLOCK_ID} />);
    await waitFor(() => {
      expect(screen.getByText(/no data points yet/i)).toBeInTheDocument();
    });
  });

  it("switches index via the combobox", async () => {
    await setupTestI18n("en");
    getTimeseriesMock.mockResolvedValue({
      block_id: BLOCK_ID,
      index_code: "ndvi",
      granularity: "daily",
      points: [],
    });
    render(<IndexTrendChart blockId={BLOCK_ID} />);
    // Two labels match /index/i (Index, Granularity); pick the
    // combobox by its explicit role+name.
    const combo = await screen.findByRole("combobox", { name: /^index$/i });
    await userEvent.selectOptions(combo, "ndwi");
    await waitFor(() => {
      const lastCallArgs = getTimeseriesMock.mock.calls.at(-1);
      expect(lastCallArgs?.[1]).toBe("ndwi");
    });
  });

  it("renders heading in arabic", async () => {
    await setupTestI18n("ar");
    getTimeseriesMock.mockResolvedValueOnce({
      block_id: BLOCK_ID,
      index_code: "ndvi",
      granularity: "daily",
      points: [],
    });
    render(<IndexTrendChart blockId={BLOCK_ID} />);
    await waitFor(() => {
      expect(screen.getByText(/اتجاه المؤشر/)).toBeInTheDocument();
    });
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
