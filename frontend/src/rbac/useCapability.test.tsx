import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

import { hasCapability } from "./useCapability";
import type { JwtClaims } from "./jwt";

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({ user: null }),
}));

describe("hasCapability", () => {
  it("denies when claims are null", () => {
    expect(hasCapability(null, "farm.create")).toBe(false);
  });

  it("allows TenantAdmin tenant-wide capabilities", () => {
    const claims: JwtClaims = { tenant_role: "TenantAdmin" };
    expect(hasCapability(claims, "farm.create")).toBe(true);
    expect(hasCapability(claims, "farm.delete")).toBe(true);
  });

  it("denies Viewer write capabilities", () => {
    const claims: JwtClaims = {
      farm_scopes: [{ farm_id: "f1", role: "Viewer" }],
    };
    expect(hasCapability(claims, "farm.update", { farmId: "f1" })).toBe(false);
    expect(hasCapability(claims, "farm.read", { farmId: "f1" })).toBe(true);
  });

  it("allows FarmManager geometry edits only on their own farm", () => {
    const claims: JwtClaims = {
      farm_scopes: [{ farm_id: "f1", role: "FarmManager" }],
    };
    expect(hasCapability(claims, "block.update_geometry", { farmId: "f1" })).toBe(true);
    expect(hasCapability(claims, "block.update_geometry", { farmId: "f2" })).toBe(false);
  });

  it("denies FarmManager from creating new farms (tenant-level decision)", () => {
    const claims: JwtClaims = {
      farm_scopes: [{ farm_id: "f1", role: "FarmManager" }],
    };
    expect(hasCapability(claims, "farm.create")).toBe(false);
  });

  it("PlatformAdmin grants every capability", () => {
    const claims: JwtClaims = { platform_role: "PlatformAdmin" };
    expect(hasCapability(claims, "farm.delete")).toBe(true);
    expect(hasCapability(claims, "block.update_geometry", { farmId: "x" })).toBe(true);
  });

  it("renderHook stub does not crash without a provider", () => {
    const { result } = renderHook(() => "ok");
    expect(result.current).toBe("ok");
  });
});
