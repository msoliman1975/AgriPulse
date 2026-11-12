import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SignalDefinition, SignalTemplate } from "@/api/signals";
import { setupTestI18n } from "@/i18n/testing";

import { SignalsPanel } from "./CatalogSignals";

const api = vi.hoisted(() => ({
  listPlatformSignalDefinitions: vi.fn(),
  listPlatformSignalTemplates: vi.fn(),
  updatePlatformSignalDefinition: vi.fn(),
  updatePlatformSignalTemplate: vi.fn(),
}));
vi.mock("@/api/signals", () => api);

function def(code: string, crop_paths: string[]): SignalDefinition {
  return {
    id: `id-${code}`,
    code,
    name: code.toUpperCase(),
    name_ar: null,
    description: null,
    description_ar: null,
    value_kind: "boolean",
    unit: null,
    unit_ar: null,
    categorical_values: null,
    categorical_values_ar: null,
    value_min: null,
    value_max: null,
    attachment_allowed: false,
    is_active: true,
    created_at: "2026-11-12T00:00:00Z",
    updated_at: "2026-11-12T00:00:00Z",
    aggregation: "latest",
    aggregation_window_days: null,
    crop_paths,
  };
}

function renderPanel(cropPath: string): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SignalsPanel cropPath={cropPath} canManage />
    </QueryClientProvider>,
  );
}

describe("<SignalsPanel>", () => {
  beforeEach(async () => {
    await setupTestI18n();
    vi.clearAllMocks();
    api.listPlatformSignalDefinitions.mockResolvedValue([
      def("date_rpw_frass", ["date_palm.medjool"]),
      def("date_dubas", ["date_palm"]),
      def("mango_hopper", ["mango"]),
      def("both_scale", ["date_palm.medjool", "mango"]),
      def("soil_moisture", []),
    ]);
    api.listPlatformSignalTemplates.mockResolvedValue([] as SignalTemplate[]);
    api.updatePlatformSignalDefinition.mockResolvedValue({});
  });

  it("splits rows scoped here, inherited from the crop above, and every-crop ones", async () => {
    renderPanel("date_palm.medjool");
    expect(await screen.findByText("DATE_RPW_FRASS")).toBeInTheDocument();
    expect(screen.getByText("DATE_DUBAS")).toBeInTheDocument();
    // A mango-only signal does not apply to a Medjool block.
    expect(screen.queryByText("MANGO_HOPPER")).not.toBeInTheDocument();
    expect(screen.getAllByText(/soil_moisture/)).toHaveLength(1);
  });

  it("removes only this path, and refuses to unscope a row's last crop", async () => {
    renderPanel("date_palm.medjool");
    await screen.findByText("BOTH_SCALE");
    const removes = screen.getAllByRole("button", { name: /Remove from this crop/i });
    // date_rpw_frass has no other crop, so it offers no remove button.
    expect(removes).toHaveLength(1);
    await userEvent.click(removes[0]);
    await waitFor(() =>
      expect(api.updatePlatformSignalDefinition).toHaveBeenCalledWith("id-both_scale", {
        crop_paths: ["mango"],
      }),
    );
  });

  it("adds a signal scoped elsewhere without dropping its other crops", async () => {
    renderPanel("date_palm.medjool");
    await screen.findByText("DATE_RPW_FRASS");
    const picker = screen.getAllByRole("combobox")[0];
    await userEvent.selectOptions(picker, "id-mango_hopper");
    await userEvent.click(screen.getAllByRole("button", { name: /^Add$/ })[0]);
    await waitFor(() =>
      expect(api.updatePlatformSignalDefinition).toHaveBeenCalledWith("id-mango_hopper", {
        crop_paths: ["date_palm.medjool", "mango"],
      }),
    );
  });
});
