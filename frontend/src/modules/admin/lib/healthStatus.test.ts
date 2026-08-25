import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { AGE_HOURS, statusFor } from "@/modules/admin/lib/healthStatus";

/**
 * Lock-step with the backend.
 *
 * The cross-tenant rollup and the Platform alerts sweep answer the same
 * question — is this stream working? — from two different code bases. When
 * their ceilings drift, one page calls a tenant healthy while the other
 * calls it critical, with nothing failing anywhere. That is what production
 * showed on 2026-08-25: the rollup said "Failing" at a fixed 24 hours while
 * the sweep's optical ceiling was 144, so no alert existed for the tenant
 * the page was flagging.
 *
 * So read the backend's own defaults rather than a copy of them.
 */
const SETTINGS = join(__dirname, "../../../../../backend/app/core/settings.py");

function backendDefault(name: string): number {
  const src = readFileSync(SETTINGS, "utf8");
  const m = new RegExp(`^\\s*${name}: int = (\\d+)`, "m").exec(src);
  if (m === null) throw new Error(`${name} not found in backend settings.py`);
  return Number(m[1]);
}

describe("PlatformHealthPage age ceilings", () => {
  it("match the platform-alert thresholds in the backend", () => {
    expect(AGE_HOURS.weather).toEqual({
      warn: backendDefault("platform_alert_weather_warn_hours"),
      crit: backendDefault("platform_alert_weather_crit_hours"),
    });
    expect(AGE_HOURS.imagery).toEqual({
      warn: backendDefault("platform_alert_optical_warn_hours"),
      crit: backendDefault("platform_alert_optical_crit_hours"),
    });
  });

  it("does not call a four-day imagery gap a failure", () => {
    const fourDaysAgo = new Date(Date.now() - 4 * 24 * 3600 * 1000).toISOString();
    expect(statusFor("imagery", fourDaysAgo, 0, 75)).toBe("ok");
  });

  it("still reports a failed job as failing, however fresh the sync", () => {
    expect(statusFor("imagery", new Date().toISOString(), 1, 75)).toBe("crit");
  });

  it("calls weather stale a day late and failing two days late", () => {
    const hoursAgo = (h: number) => new Date(Date.now() - h * 3600 * 1000).toISOString();
    expect(statusFor("weather", hoursAgo(4), 0, 1)).toBe("ok");
    expect(statusFor("weather", hoursAgo(30), 0, 1)).toBe("warn");
    expect(statusFor("weather", hoursAgo(60), 0, 1)).toBe("crit");
  });
});
