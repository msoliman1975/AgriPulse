import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConfigContext } from "@/config/ConfigContext";
import { setupTestI18n } from "@/i18n/testing";

const FARM_ID = "11111111-1111-1111-1111-111111111111";
const BLOCK_ID = "22222222-2222-2222-2222-222222222222";
const PRODUCT_ID = "33333333-3333-3333-3333-333333333333";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));

const listSubsMock = vi.hoisted(() => vi.fn());
const createSubMock = vi.hoisted(() => vi.fn());
const revokeSubMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/imagery", async () => {
  const actual = await vi.importActual<object>("@/api/imagery");
  return {
    ...actual,
    listSubscriptions: listSubsMock,
    createSubscription: createSubMock,
    revokeSubscription: revokeSubMock,
  };
});

const useCapabilityMock = vi.hoisted(() => vi.fn());
vi.mock("@/rbac/useCapability", () => ({ useCapability: useCapabilityMock }));

import { SubscriptionsTab } from "./SubscriptionsTab";

const TEST_CONFIG = {
  tile_server_base_url: "http://localhost:8001",
  s3_bucket: "agripulse-uploads",
  cloud_cover_visualization_max_pct: 60,
  cloud_cover_aggregation_max_pct: 20,
  products: [
    {
      product_id: PRODUCT_ID,
      product_code: "s2_l2a",
      product_name: "Sentinel-2 L2A",
      bands: [],
      supported_indices: [],
    },
  ],
};

function withConfig(node: React.ReactElement): React.ReactElement {
  return (
    <ConfigContext.Provider
      value={{ config: TEST_CONFIG, loading: false, error: null, reload: () => {} }}
    >
      {node}
    </ConfigContext.Provider>
  );
}

beforeEach(() => {
  listSubsMock.mockReset();
  createSubMock.mockReset();
  revokeSubMock.mockReset();
  useCapabilityMock.mockReset();
});

describe("SubscriptionsTab", () => {
  it("hides the subscribe button when imagery.subscription.manage is missing (en)", async () => {
    await setupTestI18n("en");
    listSubsMock.mockResolvedValueOnce([]);
    useCapabilityMock.mockReturnValue(false);

    render(withConfig(<SubscriptionsTab blockId={BLOCK_ID} farmId={FARM_ID} />));

    await waitFor(() => {
      expect(screen.getByText(/no subscriptions on this block yet/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /subscribe to sentinel-2 l2a/i })).toBeNull();
  });

  it("shows + invokes subscribe when the user can manage", async () => {
    await setupTestI18n("en");
    listSubsMock.mockResolvedValueOnce([]);
    useCapabilityMock.mockReturnValue(true);
    createSubMock.mockResolvedValueOnce({});
    listSubsMock.mockResolvedValueOnce([
      {
        id: "sub-1",
        block_id: BLOCK_ID,
        product_id: PRODUCT_ID,
        cadence_hours: null,
        cloud_cover_max_pct: null,
        is_active: true,
        last_successful_ingest_at: null,
        last_attempted_at: null,
        created_at: "2026-05-01T00:00:00Z",
        updated_at: "2026-05-01T00:00:00Z",
      },
    ]);

    render(withConfig(<SubscriptionsTab blockId={BLOCK_ID} farmId={FARM_ID} />));

    const subscribeBtn = await screen.findByRole("button", {
      name: /subscribe to sentinel-2 l2a/i,
    });
    await userEvent.click(subscribeBtn);

    await waitFor(() => {
      expect(createSubMock).toHaveBeenCalledWith(BLOCK_ID, { product_id: PRODUCT_ID });
    });
    // After reload, the list shows the new subscription with the
    // product name in a <p> (not the still-present subscribe button).
    await waitFor(() => {
      expect(
        screen.getByText(
          (_, el) => el?.tagName === "P" && /Sentinel-2 L2A/.test(el.textContent ?? ""),
        ),
      ).toBeInTheDocument();
    });
  });

  it("renders heading in arabic", async () => {
    await setupTestI18n("ar");
    listSubsMock.mockResolvedValueOnce([]);
    useCapabilityMock.mockReturnValue(false);

    render(withConfig(<SubscriptionsTab blockId={BLOCK_ID} farmId={FARM_ID} />));
    await screen.findByText(/اشتراكات الصور/);
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
