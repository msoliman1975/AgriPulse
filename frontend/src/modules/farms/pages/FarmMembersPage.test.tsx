import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { renderAtRoute } from "../test-utils";
import { FarmMembersPage } from "./FarmMembersPage";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: { access_token: null } }),
}));
vi.mock("@/api/farmMembers", () => ({
  listFarmMembers: vi.fn().mockResolvedValue([]),
  assignFarmMember: vi.fn(),
  revokeFarmMember: vi.fn(),
}));

describe("FarmMembersPage", () => {
  it("renders in English (LTR)", async () => {
    await setupTestI18n("en");
    renderAtRoute(<FarmMembersPage />, {
      route: "/farms/abc/members",
      path: "/farms/:farmId/members",
    });
    expect(screen.getByRole("heading", { name: "Members" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders in Arabic (RTL)", async () => {
    await setupTestI18n("ar");
    renderAtRoute(<FarmMembersPage />, {
      route: "/farms/abc/members",
      path: "/farms/:farmId/members",
    });
    expect(screen.getByRole("heading", { name: "الأعضاء" })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });
});
