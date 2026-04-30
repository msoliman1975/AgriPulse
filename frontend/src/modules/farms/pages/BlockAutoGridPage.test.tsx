import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "../test-utils";
import { BlockAutoGridPage } from "./BlockAutoGridPage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));
vi.mock("@/api/blocks", () => ({
  autoGrid: vi.fn().mockResolvedValue({ cell_size_m: 500, candidates: [] }),
  createBlock: vi.fn(),
}));

describe("BlockAutoGridPage", () => {
  it("renders the heading in English (LTR)", async () => {
    await setupTestI18n("en");
    renderAtRoute(<BlockAutoGridPage />, {
      route: "/farms/abc/blocks/auto-grid",
      path: "/farms/:farmId/blocks/auto-grid",
    });
    expect(screen.getByRole("heading", { name: "Auto-grid blocks" })).toBeInTheDocument();
    expect(screen.getByText("Compute candidates")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders the heading in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    renderAtRoute(<BlockAutoGridPage />, {
      route: "/farms/abc/blocks/auto-grid",
      path: "/farms/:farmId/blocks/auto-grid",
    });
    expect(screen.getByRole("heading", { name: "تقسيم آلي إلى شبكة" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
