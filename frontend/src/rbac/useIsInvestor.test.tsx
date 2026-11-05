import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

import { useCapability, useIsInvestor } from "./useCapability";

const mockUseAuth = vi.fn();
vi.mock("react-oidc-context", () => ({
  useAuth: () => mockUseAuth(),
}));

function jwt(payload: object): string {
  const b64 = (s: string) => btoa(s).replace(/=+$/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64("{}")}.${b64(JSON.stringify(payload))}.sig`;
}

function signIn(claims: object): void {
  mockUseAuth.mockReturnValue({ user: { access_token: jwt(claims) } });
}

describe("useIsInvestor", () => {
  it("is true for an Investor", () => {
    signIn({ tenant_role: "Investor" });
    expect(renderHook(() => useIsInvestor()).result.current).toBe(true);
  });

  it("is false for a platform admin, even though * grants the capability", () => {
    signIn({ platform_role: "PlatformAdmin" });
    expect(renderHook(() => useCapability("investor_app.use")).result.current).toBe(true);
    expect(renderHook(() => useIsInvestor()).result.current).toBe(false);
  });

  it("is false for a tenant user", () => {
    signIn({ tenant_role: "TenantAdmin" });
    expect(renderHook(() => useIsInvestor()).result.current).toBe(false);
  });
});
