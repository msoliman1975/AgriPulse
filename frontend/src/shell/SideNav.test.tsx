import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
  const b64 = (s: string) =>
    btoa(s).replace(/=+$/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64("{}")}.${b64(JSON.stringify(payload))}.sig`;
}

function renderNav(): void {
  render(
    <MemoryRouter initialEntries={["/farms"]}>
      <Routes>
        <Route path="/farms" element={<SideNav />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("<SideNav> Admin section", () => {
  it("hides the Admin section for non-platform users", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ tenant_role: "TenantAdmin" }) },
    });
    renderNav();
    expect(screen.queryByText("admin:nav.section")).not.toBeInTheDocument();
    expect(screen.queryByText("admin:nav.tenants")).not.toBeInTheDocument();
  });

  it("shows the Admin section for PlatformAdmin", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ platform_role: "PlatformAdmin" }) },
    });
    renderNav();
    expect(screen.getByText("admin:nav.section")).toBeInTheDocument();
    const link = screen.getByText("admin:nav.tenants");
    expect(link.closest("a")).toHaveAttribute("href", "/admin/tenants");
  });
});
