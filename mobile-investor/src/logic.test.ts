import { describe, expect, it } from "vitest";

import { compareVersions } from "@/api/client";
import { challengeFor, jwtClaims } from "@/auth/pkce";
import { formatFeddan, t, treeAgeYears } from "@/i18n";
import { ar } from "@/i18n/locales/ar";
import { en } from "@/i18n/locales/en";

describe("PKCE", () => {
  it("is base64url(SHA-256(verifier)) without padding", async () => {
    // Expected value from Python: urlsafe_b64encode(sha256(v)).rstrip("=").
    expect(await challengeFor("dBjftJeZ4CVP-mJ92K9IUw0zQ7akhcAWdmoU2Bl1Hk")).toBe(
      "bPeFNmja5Pd-iX2VmwUl07MbGQ-WDLps3Tg_DxhOIVU",
    );
  });

  it("reads token claims, including Arabic names", () => {
    const payload = { tenant_role: "Investor", name: "نور حسن" };
    const b64 = Buffer.from(JSON.stringify(payload)).toString("base64url");
    expect(jwtClaims(`h.${b64}.s`)).toEqual(payload);
  });
});

describe("compareVersions", () => {
  it("compares part by part as numbers", () => {
    expect(compareVersions("0.1.0", "0.2.0")).toBe(-1);
    expect(compareVersions("0.10.0", "0.9.9")).toBe(1);
    expect(compareVersions("1.0", "1.0.0")).toBe(0);
  });
});

describe("formatting", () => {
  it("prints Western digits in Arabic", () => {
    expect(formatFeddan("ar", 4200.83 * 2.5)).toBe("2.5 فدان");
    expect(formatFeddan("en", 4200.83)).toBe("1 feddan");
  });

  it("counts whole years of tree age", () => {
    const today = new Date(2026, 9, 7);
    expect(treeAgeYears("2020-10-07", today)).toBe(6);
    expect(treeAgeYears("2020-10-08", today)).toBe(5);
    expect(treeAgeYears(null, today)).toBeNull();
  });

  it("fills placeholders", () => {
    expect(t("en", "holdings.trees", { n: 412 })).toBe("412 trees");
  });

  it("has the same keys in both catalogues", () => {
    expect(Object.keys(ar).sort()).toEqual(Object.keys(en).sort());
  });
});
