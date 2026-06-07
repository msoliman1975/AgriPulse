import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { SignalDefinition, SignalObservation } from "@/api/signals";
import { setupTestI18n } from "@/i18n/testing";

const listObsMock = vi.hoisted(() => vi.fn());
const deleteObsMock = vi.hoisted(() => vi.fn().mockResolvedValue({ deleted: 1 }));
const deleteGroupMock = vi.hoisted(() => vi.fn().mockResolvedValue({ deleted: 2 }));
const listBlocksMock = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
);

vi.mock("@/api/signals", async () => {
  const actual = await vi.importActual<object>("@/api/signals");
  return {
    ...actual,
    listSignalObservations: listObsMock,
    deleteSignalObservation: deleteObsMock,
    deleteSignalTemplateObservationGroup: deleteGroupMock,
  };
});

vi.mock("@/api/blocks", async () => {
  const actual = await vi.importActual<object>("@/api/blocks");
  return { ...actual, listBlocks: listBlocksMock };
});

import { ObservationList } from "./ObservationList";

const FARM = "00000000-0000-0000-0000-000000000010";
const DEF1 = "00000000-0000-0000-0000-000000000021";
const DEF2 = "00000000-0000-0000-0000-000000000022";

function defn(id: string, name: string): SignalDefinition {
  return {
    id,
    code: name.toLowerCase(),
    name,
    description: null,
    value_kind: "numeric",
    unit: null,
    categorical_values: null,
    value_min: null,
    value_max: null,
    attachment_allowed: false,
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    aggregation: "latest",
    aggregation_window_days: null,
  };
}

function obs(p: Partial<SignalObservation> & Pick<SignalObservation, "id" | "time">): SignalObservation {
  return {
    signal_definition_id: DEF1,
    signal_code: "soilmoisture",
    farm_id: FARM,
    block_id: null,
    value_numeric: "60",
    value_categorical: null,
    value_event: null,
    value_boolean: null,
    value_geopoint: null,
    attachment_s3_key: null,
    attachment_download_url: null,
    notes: null,
    recorded_by: "u",
    inserted_at: p.time,
    location_mode: "entity",
    location_point: null,
    template_observation_id: null,
    ...p,
  };
}

const ROWS: SignalObservation[] = [
  obs({ id: "o1", time: "2026-06-03T10:00:00Z", value_numeric: "55" }),
  obs({ id: "g1", time: "2026-06-02T10:00:00Z", template_observation_id: "grp", value_numeric: "70" }),
  obs({
    id: "g2",
    time: "2026-06-02T10:00:00Z",
    template_observation_id: "grp",
    signal_definition_id: DEF2,
    value_numeric: "25",
  }),
];

function renderList(canDelete: boolean) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ObservationList
        farmId={FARM}
        definitions={[defn(DEF1, "Soil Moisture"), defn(DEF2, "Soil Temp")]}
        canDelete={canDelete}
      />
    </QueryClientProvider>,
  );
}

beforeAll(async () => {
  await setupTestI18n("en");
});

beforeEach(() => {
  listObsMock.mockReset().mockResolvedValue(ROWS);
  deleteObsMock.mockClear();
  deleteGroupMock.mockClear();
});

describe("ObservationList", () => {
  it("renders a standalone row and collapses siblings into a template group", async () => {
    renderList(false);
    expect(await screen.findByText("55")).toBeInTheDocument();
    expect(screen.getByText(/Template submission/i)).toBeInTheDocument();
    expect(screen.getByText(/2 readings/i)).toBeInTheDocument();
  });

  it("hides delete affordances without the capability and shows them with it", async () => {
    const { unmount } = renderList(false);
    await screen.findByText("55");
    expect(screen.queryAllByRole("button", { name: /^Delete$/i })).toHaveLength(0);
    unmount();

    renderList(true);
    await screen.findByText("55");
    expect(screen.getAllByRole("button", { name: /^Delete$/i }).length).toBeGreaterThan(0);
  });

  it("deletes a single observation through the confirm modal", async () => {
    const user = userEvent.setup();
    renderList(true);
    await screen.findByText("55");

    // First delete button belongs to the standalone row (rendered first).
    await user.click(screen.getAllByRole("button", { name: /^Delete$/i })[0]);
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^Delete$/i }));

    await waitFor(() => expect(deleteObsMock).toHaveBeenCalledWith("o1"));
  });
});
