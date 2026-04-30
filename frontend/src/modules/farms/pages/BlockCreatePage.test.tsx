import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "../test-utils";
import { BlockCreatePage } from "./BlockCreatePage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));
vi.mock("@/modules/farms/components/MapDraw", () => ({ MapDraw: () => null }));
vi.mock("@/modules/farms/components/MapPreview", () => ({ MapPreview: () => null }));
vi.mock("@/api/blocks", () => ({ createBlock: vi.fn() }));

describe("BlockCreatePage", () => {
  it("renders the heading in English (LTR)", async () => {
    await setupTestI18n("en");
    renderAtRoute(<BlockCreatePage />, {
      route: "/farms/abc/blocks/new",
      path: "/farms/:farmId/blocks/new",
    });
    expect(screen.getByRole("heading", { name: "Add block" })).toBeInTheDocument();
    expect(screen.getByLabelText("Block code")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders the heading in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    renderAtRoute(<BlockCreatePage />, {
      route: "/farms/abc/blocks/new",
      path: "/farms/:farmId/blocks/new",
    });
    expect(screen.getByRole("heading", { name: "إضافة قطعة" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
