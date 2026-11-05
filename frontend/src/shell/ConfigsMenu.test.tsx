import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ConfigsMenu } from "./ConfigsMenu";

const mockUseAuth = vi.fn();
vi.mock("react-oidc-context", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function jwt(payload: object): string {
  const b64 = (s: string) => btoa(s).replace(/=+$/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64("{}")}.${b64(JSON.stringify(payload))}.sig`;
}

function renderMenu(claims: object): void {
  mockUseAuth.mockReturnValue({ user: { access_token: jwt(claims) } });
  render(
    <MemoryRouter>
      <ConfigsMenu />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockUseAuth.mockReset();
});

describe("<ConfigsMenu>", () => {
  it("is offered to a tenant user", () => {
    renderMenu({ tenant_role: "TenantAdmin" });
    expect(screen.getByRole("button", { name: "shell.configsTitle" })).toBeInTheDocument();
  });

  it("is not offered to a platform admin, whose links all bounce to /platform", () => {
    renderMenu({ platform_role: "PlatformAdmin" });
    expect(screen.queryByRole("button", { name: "shell.configsTitle" })).not.toBeInTheDocument();
  });
});
