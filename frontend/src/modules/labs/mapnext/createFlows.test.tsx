import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "@/modules/farms/test-utils";
import { CreateBlockPanel, CreateFarmPanel } from "./createFlows";

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

  // The Arabic name is the one field a tenant working in Arabic cannot add
  // later from this console, so it is captured here and not behind
  // "More details".
  it("carries the Arabic name and description into the draft", async () => {
    await setupTestI18n("en");
    const { onSubmit } = renderPanel();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "SUEZ-04");
    await user.type(screen.getByLabelText("Name"), "Suez North");
    await user.type(screen.getByLabelText("Arabic name"), "  السويس الشمالية  ");
    await user.click(screen.getByRole("button", { name: /More details/ }));
    await user.type(screen.getByLabelText("Arabic description"), "وصف");
    await user.click(screen.getByRole("button", { name: "Create farm" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Suez North",
        name_ar: "السويس الشمالية",
        description_ar: "وصف",
      }),
    );
  });

  it("sends a blank Arabic name as null, not an empty string", async () => {
    await setupTestI18n("en");
    const { onSubmit } = renderPanel();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "SUEZ-05");
    await user.type(screen.getByLabelText("Name"), "Suez South");
    await user.click(screen.getByRole("button", { name: "Create farm" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ name_ar: null, description_ar: null }),
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

describe("CreateBlockPanel", () => {
  it("carries the Arabic block name into the submitted values", async () => {
    await setupTestI18n("en");
    const onSubmit = vi.fn();
    renderAtRoute(
      <CreateBlockPanel
        areaM2={42_000}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "B-12");
    await user.type(screen.getByLabelText("Name (optional)"), "North strip");
    await user.type(screen.getByLabelText("Arabic block name"), "  الشريط الشمالي  ");
    await user.click(screen.getByRole("button", { name: "Create block" }));

    expect(onSubmit).toHaveBeenCalledWith({
      code: "B-12",
      name: "North strip",
      name_ar: "الشريط الشمالي",
    });
  });

  it("sends a blank Arabic name as null", async () => {
    await setupTestI18n("en");
    const onSubmit = vi.fn();
    renderAtRoute(
      <CreateBlockPanel
        areaM2={42_000}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );
    const user = userEvent.setup();

    await user.type(screen.getByLabelText("Code"), "B-13");
    await user.click(screen.getByRole("button", { name: "Create block" }));

    expect(onSubmit).toHaveBeenCalledWith({ code: "B-13", name: "", name_ar: null });
  });
});
