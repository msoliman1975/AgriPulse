import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setupTestI18n } from "@/i18n/testing";

const FARM_ID = "11111111-1111-1111-1111-111111111111";
const BLOCK_ID = "22222222-2222-2222-2222-222222222222";
const SUB_ID = "33333333-3333-3333-3333-333333333333";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));

const listSubsMock = vi.hoisted(() => vi.fn());
const createSubMock = vi.hoisted(() => vi.fn());
const revokeSubMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/weather", async () => {
  const actual = await vi.importActual<object>("@/api/weather");
  return {
    ...actual,
    listSubscriptions: listSubsMock,
    createSubscription: createSubMock,
    revokeSubscription: revokeSubMock,
  };
});

const useCapabilityMock = vi.hoisted(() => vi.fn());
vi.mock("@/rbac/useCapability", () => ({ useCapability: useCapabilityMock }));

import { WeatherSubscriptionsTab } from "./WeatherSubscriptionsTab";

beforeEach(() => {
  void setupTestI18n();
  listSubsMock.mockReset();
  createSubMock.mockReset();
  revokeSubMock.mockReset();
  useCapabilityMock.mockReset();
  useCapabilityMock.mockReturnValue(true);
});

const sampleSub = {
  id: SUB_ID,
  block_id: BLOCK_ID,
  provider_code: "open_meteo",
  cadence_hours: null,
  is_active: true,
  last_successful_ingest_at: "2026-05-06T18:00:00Z",
  last_attempted_at: "2026-05-06T18:00:00Z",
  created_at: "2026-05-05T10:00:00Z",
  updated_at: "2026-05-05T10:00:00Z",
};

describe("WeatherSubscriptionsTab", () => {
  it("lists existing subscriptions", async () => {
    listSubsMock.mockResolvedValueOnce([sampleSub]);
    render(<WeatherSubscriptionsTab blockId={BLOCK_ID} farmId={FARM_ID} />);

    expect(await screen.findByText(/Open-Meteo/)).toBeInTheDocument();
  });

  it("subscribes when the button is clicked", async () => {
    listSubsMock.mockResolvedValueOnce([]);
    listSubsMock.mockResolvedValueOnce([sampleSub]);
    createSubMock.mockResolvedValueOnce(sampleSub);
    render(<WeatherSubscriptionsTab blockId={BLOCK_ID} farmId={FARM_ID} />);

    const subscribeButton = await screen.findByRole("button", {
      name: /subscribe to open-meteo/i,
    });
    await userEvent.click(subscribeButton);

    await waitFor(() => {
      expect(createSubMock).toHaveBeenCalledWith(BLOCK_ID, { provider_code: "open_meteo" });
    });
    // List re-fetched and the new sub is shown.
    expect(await screen.findByRole("button", { name: /^revoke/i })).toBeInTheDocument();
  });

  it("revokes when the revoke button is clicked", async () => {
    listSubsMock.mockResolvedValueOnce([sampleSub]);
    listSubsMock.mockResolvedValueOnce([]);
    revokeSubMock.mockResolvedValueOnce(undefined);
    render(<WeatherSubscriptionsTab blockId={BLOCK_ID} farmId={FARM_ID} />);

    const revokeButton = await screen.findByRole("button", { name: /^revoke/i });
    await userEvent.click(revokeButton);

    await waitFor(() => {
      expect(revokeSubMock).toHaveBeenCalledWith(BLOCK_ID, SUB_ID);
    });
  });

  it("hides the subscribe + revoke buttons when the user lacks manage capability", async () => {
    listSubsMock.mockResolvedValueOnce([sampleSub]);
    useCapabilityMock.mockReturnValue(false);
    render(<WeatherSubscriptionsTab blockId={BLOCK_ID} farmId={FARM_ID} />);

    await screen.findByText(/Open-Meteo/);
    expect(screen.queryByRole("button", { name: /^revoke/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /subscribe to open-meteo/i }),
    ).not.toBeInTheDocument();
  });

  it("shows a friendly error on duplicate subscribe (409)", async () => {
    listSubsMock.mockResolvedValueOnce([]);
    createSubMock.mockRejectedValueOnce({
      isApiError: true,
      problem: { status: 409, title: "Conflict" },
    });
    // Need our isApiError shape — easier to stub the module:
    const errorsMod = await import("@/api/errors");
    vi.spyOn(errorsMod, "isApiError").mockReturnValue(true);

    render(<WeatherSubscriptionsTab blockId={BLOCK_ID} farmId={FARM_ID} />);
    const subBtn = await screen.findByRole("button", { name: /subscribe to open-meteo/i });
    await userEvent.click(subBtn);

    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
  });
});
