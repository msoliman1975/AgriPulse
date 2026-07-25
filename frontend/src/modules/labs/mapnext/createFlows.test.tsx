import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "@/modules/farms/test-utils";
import { CreateFarmPanel } from "./createFlows";

const COUNTRIES = [
  { id: "1", code: "EG", name_en: "Egypt", name_ar: "مصر", is_active: true },
  { id: "2", code: "JO", name_en: "Jordan", name_ar: "الأردن", is_active: true },
];

function renderPanel(onSubmit = vi.fn()): { onSubmit: ReturnType<typeof vi.fn> } {
  renderAtRoute(
    <CreateFarmPanel
      areaM2={1_420_000}
      countries={COUNTRIES}
      submitting={false}
      error={null}
      onSubmit={onSubmit}
      onBack={vi.fn()}
      onCancel={vi.fn()}
    />,
  );
  return { onSubmit };
}

describe("CreateFarmPanel", () => {
  it("asks only for code, name and country up front", async () => {
    await setupTestI18n("en");
    renderPanel();

    expect(screen.getByRole("heading", { name: "New farm" })).toBeInTheDocument();
    expect(screen.getByLabelText("Code")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Country")).toBeInTheDocument();
    // The remaining farm fields stay behind "More details" — they are all
    // editable afterwards in Farm settings.
    expect(screen.queryByLabelText("Governorate")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /More details/ })).toBeInTheDocument();
  });

  it("blocks submit until a valid code and a name are present", async () => {
    await setupTestI18n("en");
    const { onSubmit } = renderPanel();
    const user = userEvent.setup();
    const create = screen.getByRole("button", { name: "Create farm" });

    expect(create).toBeDisabled();

    // A code that breaks the API pattern is rejected with the same message
    // the legacy farm form uses.
    await user.type(screen.getByLabelText("Code"), "bad code!");
    expect(create).toBeDisabled();
    expect(screen.getByText(/alphanumeric with dashes/i)).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Code"));
    await user.type(screen.getByLabelText("Code"), "SUEZ-02");
    // Still no name.
    expect(create).toBeDisabled();

    await user.type(screen.getByLabelText("Name"), "Suez East");
    expect(create).toBeEnabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits a draft with trimmed values and optional fields nulled", async () => {
    await setupTestI18n("en");
    const { onSubmit } = renderPanel();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "  SUEZ-02  ");
    await user.type(screen.getByLabelText("Name"), "  Suez East  ");
    await user.selectOptions(screen.getByLabelText("Country"), "EG");
    await user.click(screen.getByRole("button", { name: "Create farm" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        code: "SUEZ-02",
        name: "Suez East",
        country_code: "EG",
        governorate: null,
        established_date: null,
        farm_type: "commercial",
        tags: [],
      }),
    );
  });

  it("carries the optional details when More details is expanded", async () => {
    await setupTestI18n("en");
    const { onSubmit } = renderPanel();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "SUEZ-03");
    await user.type(screen.getByLabelText("Name"), "Suez West");
    await user.click(screen.getByRole("button", { name: /More details/ }));
    await user.type(screen.getByLabelText("Governorate"), "Suez");
    await user.type(screen.getByLabelText("Tags"), " drip , mango ");
    await user.click(screen.getByRole("button", { name: "Create farm" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ governorate: "Suez", tags: ["drip", "mango"] }),
    );
  });

  it("renders in Arabic with RTL direction", async () => {
    await setupTestI18n("ar");
    renderPanel();

    expect(screen.getByRole("heading", { name: "مزرعة جديدة" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "إنشاء مزرعة" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
