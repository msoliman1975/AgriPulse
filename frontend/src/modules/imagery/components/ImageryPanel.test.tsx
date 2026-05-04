import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ConfigContext } from "@/config/ConfigContext";
import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "@/modules/farms/test-utils";

const FARM_ID = "11111111-1111-1111-1111-111111111111";
const BLOCK_ID = "22222222-2222-2222-2222-222222222222";

// Mock the WebGL bits — jsdom can't render maplibre + deck.gl.
vi.mock("./NDVIMap", () => ({
  NDVIMap: ({ tileUrlTemplate }: { tileUrlTemplate: string | null }) => (
    <div data-testid="ndvi-map">{tileUrlTemplate ?? "no-tiles"}</div>
  ),
}));

// API mocks.
vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));

const listScenesMock = vi.hoisted(() => vi.fn());
const triggerRefreshMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/imagery", async () => {
  const actual = await vi.importActual<object>("@/api/imagery");
  return { ...actual, listScenes: listScenesMock, triggerRefresh: triggerRefreshMock };
});

// Stub the user's capability set: this module's `useCapability` reads
// from RequestContext; the simplest path is to mock the hook directly.
const useCapabilityMock = vi.hoisted(() => vi.fn());
vi.mock("@/rbac/useCapability", () => ({ useCapability: useCapabilityMock }));

const TEST_CONFIG = {
  tile_server_base_url: "http://localhost:8001",
  s3_bucket: "missionagre-uploads",
  cloud_cover_visualization_max_pct: 60,
  cloud_cover_aggregation_max_pct: 20,
  products: [
    {
      product_id: "33333333-3333-3333-3333-333333333333",
      product_code: "s2_l2a",
      product_name: "Sentinel-2 L2A",
      bands: ["blue", "green", "red", "red_edge_1", "nir", "swir1", "swir2"],
      supported_indices: ["ndvi", "ndwi", "evi", "savi", "ndre", "gndvi"],
    },
  ],
};

import { ImageryPanel } from "./ImageryPanel";

function withConfig(node: React.ReactElement): React.ReactElement {
  return (
    <ConfigContext.Provider
      value={{
        config: TEST_CONFIG,
        loading: false,
        error: null,
        reload: () => {},
      }}
    >
      {node}
    </ConfigContext.Provider>
  );
}

const sampleGeometry = {
  type: "Polygon" as const,
  coordinates: [
    [
      [31.2, 30.1],
      [31.21, 30.1],
      [31.21, 30.11],
      [31.2, 30.11],
      [31.2, 30.1],
    ],
  ],
};

beforeEach(() => {
  listScenesMock.mockReset();
  triggerRefreshMock.mockReset();
  useCapabilityMock.mockReset();
});

describe("ImageryPanel", () => {
  it("renders empty state when no succeeded scenes are present (en)", async () => {
    await setupTestI18n("en");
    listScenesMock.mockResolvedValueOnce({ items: [], next_cursor: null });
    useCapabilityMock.mockReturnValue(false); // no refresh capability

    render(
      withConfig(
        <ImageryPanel
          blockId={BLOCK_ID}
          farmId={FARM_ID}
          geometry={sampleGeometry}
          aoiHash="abc123"
        />,
      ),
    );

    await waitFor(() => {
      expect(screen.getByText("No scenes ingested yet for this block.")).toBeInTheDocument();
    });
    // Refresh button hidden without imagery.refresh.
    expect(screen.queryByRole("button", { name: /refresh imagery/i })).toBeNull();
  });

  it("shows refresh button when imagery.refresh is granted", async () => {
    await setupTestI18n("en");
    listScenesMock.mockResolvedValueOnce({ items: [], next_cursor: null });
    triggerRefreshMock.mockResolvedValueOnce({
      queued_subscription_ids: ["sub-1"],
      correlation_id: null,
    });
    useCapabilityMock.mockReturnValue(true);

    render(
      withConfig(
        <ImageryPanel
          blockId={BLOCK_ID}
          farmId={FARM_ID}
          geometry={sampleGeometry}
          aoiHash="abc123"
        />,
      ),
    );

    const button = await screen.findByRole("button", { name: /refresh imagery/i });
    await userEvent.click(button);
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(/queued 1 subscription/i);
    });
  });

  it("renders scene picker + tile URL when scenes exist (ar locale)", async () => {
    await setupTestI18n("ar");
    listScenesMock.mockResolvedValueOnce({
      items: [
        {
          id: "job-1",
          block_id: BLOCK_ID,
          subscription_id: "sub-1",
          product_id: TEST_CONFIG.products[0].product_id,
          scene_id: "S2A_TEST_SCENE",
          scene_datetime: "2026-05-01T10:00:00Z",
          requested_at: "2026-05-01T10:01:00Z",
          started_at: "2026-05-01T10:02:00Z",
          completed_at: "2026-05-01T10:05:00Z",
          status: "succeeded",
          cloud_cover_pct: "12.50",
          valid_pixel_pct: "85.00",
          error_message: null,
          stac_item_id: "sentinel_hub/s2_l2a/S2A_TEST_SCENE/abc123",
        },
      ],
      next_cursor: null,
    });
    useCapabilityMock.mockReturnValue(true);

    render(
      withConfig(
        <ImageryPanel
          blockId={BLOCK_ID}
          farmId={FARM_ID}
          geometry={sampleGeometry}
          aoiHash="abc123"
        />,
      ),
    );

    // Wait for the scene picker to mount.
    const select = await screen.findByLabelText(/المشهد/);
    expect(select).toBeInTheDocument();
    // The mocked NDVIMap surfaces the tile-URL template — assert it
    // contains the index COG asset path and the rescale window.
    await waitFor(() => {
      const map = screen.getByTestId("ndvi-map");
      expect(map.textContent).toContain("ndvi.tif");
      expect(map.textContent).toContain("rescale=-0.2");
    });
    // Document <html dir="rtl"> while in ar.
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});

// Suppress unused-import warning when these only feature in mocks.
const _ = renderAtRoute;
void _;
