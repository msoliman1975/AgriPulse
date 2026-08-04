import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { SideNav } from "./SideNav";

const mockUseAuth = vi.fn();
vi.mock("react-oidc-context", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: (ns?: string) => ({
    t: (key: string) => `${ns ?? "common"}:${key}`,
  }),
}));

function jwt(payload: object): string {
  const b64 = (s: string) => btoa(s).replace(/=+$/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64("{}")}.${b64(JSON.stringify(payload))}.sig`;
}

function renderNav(): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={["/farms"]}>
      <Routes>
        <Route path="/farms" element={<SideNav />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("<SideNav> Admin section", () => {
  it("hides the Admin section for non-platform users", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ tenant_role: "TenantAdmin" }) },
    });
    renderNav();
    expect(screen.queryByText("admin,common:nav.section")).not.toBeInTheDocument();
    expect(screen.queryByText("admin,common:nav.tenants")).not.toBeInTheDocument();
  });

  it("shows the Admin section for PlatformAdmin", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ platform_role: "PlatformAdmin" }) },
    });
    renderNav();
    expect(screen.getByText("admin,common:nav.section")).toBeInTheDocument();
    const link = screen.getByText("admin,common:nav.tenants");
    expect(link.closest("a")).toHaveAttribute("href", "/platform/tenants");
  });
});

describe("<SideNav> collapse", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ tenant_role: "TenantAdmin" }) },
    });
  });

  it("collapses to an icons-only rail and remembers the choice", () => {
    const { unmount } = renderNav();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav.className).toContain("w-56");
    expect(screen.getByText("admin,common:common:workspaceNav.workspace")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "common:workspaceNav.collapse" }));

    expect(nav.className).toContain("w-14");
    expect(nav.className).not.toContain("w-56");
    // The group heading goes with the labels, but every destination keeps its
    // label in the accessibility tree so the rail stays navigable.
    expect(
      screen.queryByText("admin,common:common:workspaceNav.workspace"),
    ).not.toBeInTheDocument();
    const farmMgmt = screen.getByText("admin,common:common:workspaceNav.farmManagement");
    expect(farmMgmt).toHaveClass("sr-only");
    expect(farmMgmt.closest("a")).toHaveAttribute(
      "title",
      "admin,common:common:workspaceNav.farmManagement",
    );

    unmount();
    renderNav();
    expect(screen.getByRole("navigation", { name: "Primary" }).className).toContain("w-14");
    expect(screen.getByRole("button", { name: "common:workspaceNav.expand" })).toBeInTheDocument();
  });
});
