import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { PlatformAdminGuard } from "./PlatformAdminGuard";

const mockUseAuth = vi.fn();
vi.mock("react-oidc-context", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Build a minimal JWT with the given claims (header.payload.signature).
function jwt(payload: object): string {
  const b64 = (s: string) => btoa(s).replace(/=+$/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64("{}")}.${b64(JSON.stringify(payload))}.sig`;
}

describe("<PlatformAdminGuard>", () => {
  it("renders children when JWT carries platform_role=PlatformAdmin", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ platform_role: "PlatformAdmin" }) },
    });
    render(
      <PlatformAdminGuard>
        <p>secret-content</p>
      </PlatformAdminGuard>,
    );
    expect(screen.getByText("secret-content")).toBeInTheDocument();
  });

  it("renders the 403 panel when the user lacks platform.manage_tenants", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ tenant_role: "TenantAdmin" }) },
    });
    render(
      <PlatformAdminGuard>
        <p>secret-content</p>
      </PlatformAdminGuard>,
    );
    expect(screen.queryByText("secret-content")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("guard.forbiddenTitle")).toBeInTheDocument();
  });

  it("renders the 403 panel when no token is present", () => {
    mockUseAuth.mockReturnValue({ user: null });
    render(
      <PlatformAdminGuard>
        <p>secret-content</p>
      </PlatformAdminGuard>,
    );
    expect(screen.queryByText("secret-content")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
