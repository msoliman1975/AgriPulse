/**
 * The shared block health editor: what it shows for an inherited value, and
 * what one switch does to the body it reports.
 *
 * The inherited rows copy the shape `GET /v1/admin/health-definitions/crops/
 * {crop_path}` returns (`CropPathView` in
 * `backend/app/modules/health/admin_router.py`).
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HealthBody, InheritedValue } from "@/api/healthDefinitions";
import { setupTestI18n } from "@/i18n/testing";

import { HealthDefinitionEditor } from "./HealthDefinitionEditor";

const INHERITED: Record<string, InheritedValue> = {
  stale_after_hours: { value: 72, source: "mango" },
  severity_map: {
    value: { critical: "critical", warning: "watch", info: "healthy" },
    source: "platform",
  },
  recommendation_floor: { value: null, source: "platform" },
};

describe("HealthDefinitionEditor", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("shows an inherited value and the level it came from", async () => {
    render(
      <HealthDefinitionEditor
        keys={["stale_after_hours", "recommendation_floor"]}
        values={{}}
        inherited={INHERITED}
        onChange={vi.fn()}
        disabled={false}
      />,
    );
    expect(await screen.findByText("72 hours")).toBeInTheDocument();
    expect(screen.getByText("from mango")).toBeInTheDocument();
    expect(screen.getByText("Recommendations never change health")).toBeInTheDocument();
    expect(screen.getByText("from platform default")).toBeInTheDocument();
  });

  it("starts a switched-on value from the inherited one, not from a default", async () => {
    const onChange = vi.fn<(next: HealthBody) => void>();
    render(
      <HealthDefinitionEditor
        keys={["stale_after_hours", "severity_map"]}
        values={{}}
        inherited={INHERITED}
        onChange={onChange}
        disabled={false}
      />,
    );
    await userEvent.click(await screen.findByRole("checkbox", { name: /Set Alert severity/ }));
    const body = onChange.mock.calls[0]![0];
    expect(body).toEqual({
      severity_map: { critical: "critical", warning: "watch", info: "healthy" },
    });
    // A copy: editing the body must never edit the inherited object.
    expect(body.severity_map).not.toBe(INHERITED.severity_map!.value);
  });

  it("drops a key when its switch goes off", async () => {
    const onChange = vi.fn<(next: HealthBody) => void>();
    render(
      <HealthDefinitionEditor
        keys={["stale_after_hours"]}
        values={{ stale_after_hours: 24 }}
        inherited={INHERITED}
        onChange={onChange}
        disabled={false}
      />,
    );
    expect(await screen.findByRole("spinbutton")).toHaveValue(24);
    await userEvent.click(screen.getByRole("checkbox", { name: /Set Trust a clear result/ }));
    expect(onChange).toHaveBeenCalledWith({});
  });

  it("has no switches without inherited values, and keeps null as a choice", async () => {
    const onChange = vi.fn<(next: HealthBody) => void>();
    render(
      <HealthDefinitionEditor
        keys={["recommendation_floor"]}
        values={{ recommendation_floor: 0.8 }}
        onChange={onChange}
        disabled={false}
      />,
    );
    expect(await screen.findByRole("spinbutton")).toHaveValue(80);
    await userEvent.click(screen.getByRole("checkbox", { name: "Set a threshold" }));
    expect(onChange).toHaveBeenCalledWith({ recommendation_floor: null });
  });
});
