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

/**
 * The served grants are what make runtime permission edits visible without a
 * redeploy. The bundled mirror stays as the pre-`/v1/me` fallback, which is
 * why every test above still passes unchanged.
 */
describe("hasCapability with grants served by /v1/me", () => {
  const claims: JwtClaims = { farm_scopes: [{ farm_id: "f1", role: "Agronomist" }] };

  it("grants what the server grants but the bundled mirror does not", () => {
    expect(hasCapability(claims, "plan.manage", { farmId: "f1" })).toBe(false);
    expect(
      hasCapability(claims, "plan.manage", { farmId: "f1" }, { Agronomist: ["plan.manage"] }),
    ).toBe(true);
  });

  it("revokes what the server revokes, even though the mirror grants it", () => {
    expect(hasCapability(claims, "alert.read", { farmId: "f1" })).toBe(true);
    expect(
      hasCapability(claims, "alert.read", { farmId: "f1" }, { Agronomist: ["plan.manage"] }),
    ).toBe(false);
  });

  it("treats an empty served list as a real answer, not as missing data", () => {
    // The dangerous misreading: falling back to the bundled defaults here would
    // silently restore every capability the admin just removed.
    expect(hasCapability(claims, "alert.read", { farmId: "f1" }, { Agronomist: [] })).toBe(false);
  });

  it("falls back to the mirror for a role the server did not describe", () => {
    expect(hasCapability(claims, "alert.read", { farmId: "f1" }, { Scout: [] })).toBe(true);
  });

  it("still honours the wildcard when served", () => {
    const admin: JwtClaims = { platform_role: "PlatformAdmin" };
    expect(hasCapability(admin, "farm.delete", {}, { PlatformAdmin: ["*"] })).toBe(true);
  });

  it("keeps a served farm grant scoped to the matching farm", () => {
    const served = { Agronomist: ["plan.manage"] };
    expect(hasCapability(claims, "plan.manage", { farmId: "f2" }, served)).toBe(false);
  });
});
