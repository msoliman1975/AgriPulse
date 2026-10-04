import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfigProvider } from "./ConfigContext";

const mockUseAuth = vi.fn();
vi.mock("react-oidc-context", () => ({
  useAuth: () => mockUseAuth(),
}));

const getConfig = vi.fn();
vi.mock("@/api/config", () => ({
  getConfig: () => getConfig(),
}));

function jwt(payload: object): string {
  const b64 = (s: string) => btoa(s).replace(/=+$/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64("{}")}.${b64(JSON.stringify(payload))}.sig`;
}

beforeEach(() => {
  getConfig.mockReset();
  getConfig.mockResolvedValue({});
});

describe("<ConfigProvider>", () => {
  it("does not call /v1/config for a platform admin with no tenant", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ platform_role: "PlatformAdmin" }) },
    });
    render(<ConfigProvider>child</ConfigProvider>);
    expect(getConfig).not.toHaveBeenCalled();
  });

  it("calls /v1/config when the token names a tenant", () => {
    mockUseAuth.mockReturnValue({
      user: { access_token: jwt({ tenant_id: "t-1", tenant_role: "TenantOwner" }) },
    });
    render(<ConfigProvider>child</ConfigProvider>);
    expect(getConfig).toHaveBeenCalledTimes(1);
  });
});
