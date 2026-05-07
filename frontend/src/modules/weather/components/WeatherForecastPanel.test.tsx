import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setupTestI18n } from "@/i18n/testing";
import { PrefsProvider } from "@/prefs/PrefsContext";

const FARM_ID = "11111111-1111-1111-1111-111111111111";
const BLOCK_ID = "22222222-2222-2222-2222-222222222222";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));

const getForecastMock = vi.hoisted(() => vi.fn());
const triggerRefreshMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/weather", async () => {
  const actual = await vi.importActual<object>("@/api/weather");
  return {
    ...actual,
    getForecast: getForecastMock,
    triggerRefresh: triggerRefreshMock,
  };
});

const useCapabilityMock = vi.hoisted(() => vi.fn());
vi.mock("@/rbac/useCapability", () => ({ useCapability: useCapabilityMock }));

import { WeatherForecastPanel } from "./WeatherForecastPanel";

beforeEach(() => {
  void setupTestI18n();
  getForecastMock.mockReset();
  triggerRefreshMock.mockReset();
  useCapabilityMock.mockReset();
  // Default: user has refresh permission unless overridden.
  useCapabilityMock.mockReturnValue(true);
  // Reset any persisted weather unit so each test starts metric.
  window.localStorage.clear();
});

function renderPanel(): ReturnType<typeof render> {
  return render(
    <PrefsProvider>
      <WeatherForecastPanel blockId={BLOCK_ID} farmId={FARM_ID} />
    </PrefsProvider>,
  );
}

const sampleForecast = {
  farm_id: FARM_ID,
  provider_code: "open_meteo",
  timezone: "Africa/Cairo",
  forecast_issued_at: "2026-05-06T18:00:00Z",
  days: [
    {
      date: "2026-05-06",
      high_c: "30.5",
      low_c: "22.0",
      precip_mm_total: "0.0",
      precip_probability_max_pct: "10.0",
    },
    {
      date: "2026-05-07",
      high_c: "32.0",
      low_c: "23.0",
      precip_mm_total: "5.5",
      precip_probability_max_pct: "80.0",
    },
  ],
};

describe("WeatherForecastPanel", () => {
  it("renders the 5-day forecast grid with day labels", async () => {
    getForecastMock.mockResolvedValueOnce(sampleForecast);
    renderPanel();

    expect(await screen.findByText("Today")).toBeInTheDocument();
    expect(screen.getByText("Tomorrow")).toBeInTheDocument();
    // Highs displayed (metric default).
    expect(screen.getByText(/31°/)).toBeInTheDocument(); // 30.5 -> 31° at 0 decimals
    expect(screen.getByText(/32°/)).toBeInTheDocument();
    // Precip and probability per day.
    expect(screen.getByText(/Chance: 80%/)).toBeInTheDocument();
  });

  it("triggers a refresh when the button is clicked", async () => {
    getForecastMock.mockResolvedValue(sampleForecast);
    triggerRefreshMock.mockResolvedValueOnce({
      queued_farm_ids: [FARM_ID],
      correlation_id: null,
    });
    renderPanel();

    const button = await screen.findByRole("button", { name: /refresh weather/i });
    await userEvent.click(button);

    await waitFor(() => {
      expect(triggerRefreshMock).toHaveBeenCalledWith(BLOCK_ID);
    });
    expect(await screen.findByText(/queued/i)).toBeInTheDocument();
  });

  it("hides the refresh button when the user lacks weather.refresh", async () => {
    getForecastMock.mockResolvedValueOnce(sampleForecast);
    useCapabilityMock.mockReturnValue(false);
    renderPanel();

    await screen.findByText("Today");
    expect(screen.queryByRole("button", { name: /refresh weather/i })).not.toBeInTheDocument();
  });

  it("shows an empty-state message when the forecast has no days", async () => {
    getForecastMock.mockResolvedValueOnce({ ...sampleForecast, days: [] });
    renderPanel();

    expect(await screen.findByText(/no forecast data/i)).toBeInTheDocument();
  });

  it("surfaces an API error", async () => {
    getForecastMock.mockRejectedValueOnce(new Error("network down"));
    renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent(/network down/);
  });
});
