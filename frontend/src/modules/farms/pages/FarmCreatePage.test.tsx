import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "../test-utils";
import { FarmCreatePage } from "./FarmCreatePage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));
vi.mock("@/modules/farms/components/MapDraw", () => ({ MapDraw: () => null }));
vi.mock("@/modules/farms/components/MapPreview", () => ({ MapPreview: () => null }));

describe("FarmCreatePage", () => {
  it("renders the form in English (LTR)", async () => {
    await setupTestI18n("en");
    renderAtRoute(<FarmCreatePage />, { route: "/farms/new", path: "/farms/new" });
    expect(screen.getByRole("heading", { name: "New farm" })).toBeInTheDocument();
    expect(screen.getByLabelText("Code")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders the form in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    renderAtRoute(<FarmCreatePage />, { route: "/farms/new", path: "/farms/new" });
    expect(screen.getByRole("heading", { name: "مزرعة جديدة" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
