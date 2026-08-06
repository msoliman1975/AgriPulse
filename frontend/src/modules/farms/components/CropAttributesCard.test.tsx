import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { CropAttributesCard } from "./CropAttributesCard";

// The card is what's under test; stub the network. `putBlockCropAttributes`
// echoes back what it was given so the save path can be asserted on.
const getAttributes = vi.fn();
const putAttributes = vi.fn();
const getHistory = vi.fn();

vi.mock("@/api/cropAssignments", () => ({
  getBlockCropAttributes: (...args: unknown[]) => getAttributes(...args),
  putBlockCropAttributes: (...args: unknown[]) => putAttributes(...args),
  getBlockCropAttributeHistory: (...args: unknown[]) => getHistory(...args),
}));

// Capability checks hit the auth store; the card's gating is the subject.
vi.mock("@/rbac/useCapability", () => ({ useCapability: () => true }));

const GATE = { code: "establishment_method", in: ["grafted_tree"] };

const DEFINITIONS = [
  {
    id: "d1",
    crop_id: "c",
    crop_variety_id: null,
    crop_variety_strain_id: null,
    path: "mango",
    code: "establishment_method",
    name_en: "Establishment method",
    name_ar: "طريقة التأسيس",
    description_en: null,
    description_ar: null,
    value_type: "single_select",
    unit_en: null,
    unit_ar: null,
    value_min: null,
    value_max: null,
    decimal_places: null,
    text_max_length: null,
    options: [
      { code: "seed", name_en: "Seed", name_ar: "بذرة", sort_order: 1 },
      { code: "grafted_tree", name_en: "Grafted tree", name_ar: "شجرة مطعمة", sort_order: 2 },
    ],
    is_required: true,
    required_when: null,
    show_when: null,
    group_code: "establishment",
    group_name_en: "Establishment",
    group_name_ar: "التأسيس",
    sort_order: 1,
    is_reportable: true,
    is_active: true,
  },
  {
    id: "d2",
    crop_id: "c",
    crop_variety_id: null,
    crop_variety_strain_id: null,
    path: "mango",
    code: "transplant_date",
    name_en: "Transplant date",
    name_ar: "تاريخ الشتل",
    description_en: null,
    description_ar: null,
    value_type: "date",
    unit_en: null,
    unit_ar: null,
    value_min: null,
    value_max: null,
    decimal_places: null,
    text_max_length: null,
    options: null,
    is_required: false,
    required_when: GATE,
    show_when: GATE,
    group_code: "establishment",
    group_name_en: "Establishment",
    group_name_ar: "التأسيس",
    sort_order: 2,
    is_reportable: true,
    is_active: true,
  },
];

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CropAttributesCard blockCropId="bc-1" farmId="f-1" />
    </QueryClientProvider>,
  );
}

describe("<CropAttributesCard>", () => {
  beforeEach(async () => {
    await setupTestI18n("en");
    getAttributes.mockReset();
    putAttributes.mockReset();
    getHistory.mockReset();
    getAttributes.mockResolvedValue({
      block_crop_id: "bc-1",
      crop_path: "mango.sukkary",
      definitions: DEFINITIONS,
      values: {},
    });
    putAttributes.mockImplementation((_id: string, attributes: Record<string, unknown>) =>
      Promise.resolve({
        block_crop_id: "bc-1",
        crop_path: "mango.sukkary",
        definitions: DEFINITIONS,
        values: Object.fromEntries(
          Object.entries(attributes).filter(([, v]) => v !== null && v !== undefined),
        ),
      }),
    );
  });

  it("renders nothing for a crop with no attributes", async () => {
    getAttributes.mockResolvedValue({
      block_crop_id: "bc-1",
      crop_path: "wheat",
      definitions: [],
      values: {},
    });
    const { container } = render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <CropAttributesCard blockCropId="bc-1" farmId="f-1" />
      </QueryClientProvider>,
    );
    // An empty "Crop fields" heading on every non-tree block would be noise.
    await waitFor(() => expect(container.textContent).not.toContain("Loading"));
    expect(screen.queryByText("Establishment")).not.toBeInTheDocument();
  });

  it("hides a gated field until its gate opens, then requires it", async () => {
    const user = userEvent.setup();
    renderCard();

    await screen.findByText("Establishment");
    expect(screen.queryByLabelText(/Transplant date/)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/Establishment method/), "grafted_tree");

    const date = await screen.findByLabelText(/Transplant date/);
    expect(date).toBeInTheDocument();
    // Required by its gate, and empty → save must stay blocked.
    expect(screen.getByRole("button", { name: /Save fields/ })).toBeDisabled();
  });

  it("warns before a closing gate discards a value, and sends an explicit null", async () => {
    getAttributes.mockResolvedValue({
      block_crop_id: "bc-1",
      crop_path: "mango.sukkary",
      definitions: DEFINITIONS,
      values: { establishment_method: "grafted_tree", transplant_date: "2023-02-18" },
    });
    const user = userEvent.setup();
    renderCard();

    await screen.findByDisplayValue("2023-02-18");
    await user.selectOptions(screen.getByLabelText(/Establishment method/), "seed");

    // The value disappearing from the form should never be a surprise.
    expect(await screen.findByText(/will clear transplant_date/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Save fields/ }));

    await waitFor(() => expect(putAttributes).toHaveBeenCalledTimes(1));
    expect(putAttributes.mock.calls[0][1]).toEqual({
      establishment_method: "seed",
      transplant_date: null,
    });
  });

  it("surfaces the server's rejection rather than a generic failure", async () => {
    const { ApiError } = await import("@/api/errors");
    putAttributes.mockRejectedValue(
      new ApiError({
        type: "x",
        title: "Invalid",
        status: 422,
        detail: "age_at_transplant_months: 9999 is above the maximum 600",
      }),
    );
    const user = userEvent.setup();
    renderCard();

    await screen.findByText("Establishment");
    await user.selectOptions(screen.getByLabelText(/Establishment method/), "seed");
    await user.click(screen.getByRole("button", { name: /Save fields/ }));

    expect(await screen.findByText(/above the maximum 600/)).toBeInTheDocument();
  });
});
