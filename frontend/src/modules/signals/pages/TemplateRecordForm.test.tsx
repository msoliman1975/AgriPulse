import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  SignalDefinition,
  SignalTemplate,
  SignalTemplateWithMembers,
} from "@/api/signals";
import { setupTestI18n } from "@/i18n/testing";

const createTemplateObservationMock = vi.hoisted(() =>
  vi.fn().mockResolvedValue({
    template_observation_id: "00000000-0000-0000-0000-000000000099",
    template_id: "00000000-0000-0000-0000-000000000001",
    farm_id: "00000000-0000-0000-0000-000000000010",
    block_id: null,
    observed_at: "2026-05-20T09:00:00.000Z",
    observation_count: 2,
  }),
);
const getSignalTemplateMock = vi.hoisted(() => vi.fn());
const listBlocksMock = vi.hoisted(() =>
  vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
);

vi.mock("@/api/signals", async () => {
  const actual = await vi.importActual<object>("@/api/signals");
  return {
    ...actual,
    createSignalTemplateObservation: createTemplateObservationMock,
    getSignalTemplate: getSignalTemplateMock,
  };
});

vi.mock("@/api/blocks", async () => {
  const actual = await vi.importActual<object>("@/api/blocks");
  return {
    ...actual,
    listBlocks: listBlocksMock,
  };
});

import { TemplateRecordForm } from "./SignalsLogPage";

const TEMPLATE_ID = "00000000-0000-0000-0000-000000000001";
const FARM_ID = "00000000-0000-0000-0000-000000000010";
const DEF_PH_ID = "00000000-0000-0000-0000-000000000020";
const DEF_N_ID = "00000000-0000-0000-0000-000000000021";

function defn(id: string, code: string, name: string): SignalDefinition {
  return {
    id,
    code,
    name,
    description: null,
    value_kind: "numeric",
    unit: null,
    categorical_values: null,
    value_min: null,
    value_max: null,
    attachment_allowed: false,
    is_active: true,
    created_at: "2026-05-01T00:00:00Z",
    updated_at: "2026-05-01T00:00:00Z",
    aggregation: "latest",
    aggregation_window_days: null,
  };
}

const template: SignalTemplate = {
  id: TEMPLATE_ID,
  code: "soil_test",
  name: "Soil test",
  description: "Lab panel",
  is_active: true,
  created_at: "2026-05-01T00:00:00Z",
  updated_at: "2026-05-01T00:00:00Z",
};

const definitions: SignalDefinition[] = [
  defn(DEF_PH_ID, "ph", "Soil pH"),
  defn(DEF_N_ID, "nitrogen", "Nitrogen"),
];

const detail: SignalTemplateWithMembers = {
  template,
  members: [
    { signal_definition_id: DEF_PH_ID, position: 0, is_required: true },
    { signal_definition_id: DEF_N_ID, position: 1, is_required: false },
  ],
};

function renderForm() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TemplateRecordForm template={template} farmId={FARM_ID} definitions={definitions} />
    </QueryClientProvider>,
  );
}

describe("<TemplateRecordForm>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    createTemplateObservationMock.mockClear();
    getSignalTemplateMock.mockReset();
    getSignalTemplateMock.mockResolvedValue(detail);
  });

  it("submits one member submission per filled member, sharing observed_at", async () => {
    const user = userEvent.setup();
    renderForm();

    // Wait for the form to hydrate (members render once getSignalTemplate resolves).
    await screen.findByText("Soil pH");

    // Both numeric inputs exist now.
    const numericInputs = screen
      .getAllByRole("textbox")
      .filter((el) => (el as HTMLInputElement).inputMode === "decimal");
    expect(numericInputs).toHaveLength(2);

    await user.type(numericInputs[0], "6.8");
    await user.type(numericInputs[1], "12");

    const observedAt = screen.getByLabelText(/observed at/i);
    await user.type(observedAt, "2026-05-20T09:00");

    await user.click(screen.getByRole("button", { name: /record observations/i }));

    await waitFor(() => expect(createTemplateObservationMock).toHaveBeenCalledTimes(1));
    const [templateId, payload] = createTemplateObservationMock.mock.calls[0];
    expect(templateId).toBe(TEMPLATE_ID);
    expect(payload.farm_id).toBe(FARM_ID);
    expect(payload.members).toHaveLength(2);
    expect(payload.members[0]).toMatchObject({
      signal_definition_id: DEF_PH_ID,
      value_numeric: "6.8",
    });
    expect(payload.members[1]).toMatchObject({
      signal_definition_id: DEF_N_ID,
      value_numeric: "12",
    });
    expect(typeof payload.observed_at).toBe("string");
    expect(payload.observed_at).toMatch(/^\d{4}-/);
  });

  it("blocks submission when a required member is empty", async () => {
    const user = userEvent.setup();
    renderForm();

    const inputs = await screen.findAllByRole("textbox").then((els) =>
      els.filter((el) => (el as HTMLInputElement).inputMode === "decimal"),
    );
    // Only fill the optional member; required ph stays empty.
    await user.type(inputs[1], "12");

    await user.click(screen.getByRole("button", { name: /record observations/i }));

    // The mutation should NOT have fired and an error should be visible.
    expect(createTemplateObservationMock).not.toHaveBeenCalled();
    expect(screen.getByText(/Soil pH is required/i)).toBeInTheDocument();
  });

  it("omits observed_at when the picker is untouched (server backfills now())", async () => {
    const user = userEvent.setup();
    renderForm();

    const inputs = await screen.findAllByRole("textbox").then((els) =>
      els.filter((el) => (el as HTMLInputElement).inputMode === "decimal"),
    );
    await user.type(inputs[0], "6.8");

    await user.click(screen.getByRole("button", { name: /record observations/i }));

    await waitFor(() => expect(createTemplateObservationMock).toHaveBeenCalledTimes(1));
    const [, payload] = createTemplateObservationMock.mock.calls[0];
    expect(payload.observed_at).toBeNull();
  });
});
