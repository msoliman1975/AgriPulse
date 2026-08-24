import { describe, expect, it } from "vitest";

import {
  IDENTITY_VIEWPORT,
  MAX_SCALE,
  MIN_SCALE,
  clampScale,
  fitToViewport,
  screenToWorld,
  worldToScreen,
  zoomAt,
  zoomAtCentre,
  zoomPercent,
} from "./canvasViewport";

describe("clampScale", () => {
  it("holds the scale inside the allowed band", () => {
    expect(clampScale(0.01)).toBe(MIN_SCALE);
    expect(clampScale(99)).toBe(MAX_SCALE);
    expect(clampScale(1.4)).toBe(1.4);
  });

  it("falls back to 1 for a non-finite scale", () => {
    expect(clampScale(Number.NaN)).toBe(1);
    expect(clampScale(Number.POSITIVE_INFINITY)).toBe(1);
  });
});

describe("screenToWorld / worldToScreen", () => {
  it("round-trips a point", () => {
    const view = { scale: 1.75, tx: -120, ty: 64 };
    const world = screenToWorld(view, 300, 210);
    const screen = worldToScreen(view, world.x, world.y);
    expect(screen.x).toBeCloseTo(300, 6);
    expect(screen.y).toBeCloseTo(210, 6);
  });
});

describe("zoomAt", () => {
  it("keeps the anchored point under the cursor", () => {
    const view = { scale: 1, tx: 0, ty: 0 };
    const anchorX = 420;
    const anchorY = 180;
    const before = screenToWorld(view, anchorX, anchorY);
    const next = zoomAt(view, 1.2, anchorX, anchorY);
    const after = screenToWorld(next, anchorX, anchorY);
    expect(next.scale).toBeCloseTo(1.2, 6);
    expect(after.x).toBeCloseTo(before.x, 6);
    expect(after.y).toBeCloseTo(before.y, 6);
  });

  it("returns the same viewport once the scale is pinned at a limit", () => {
    const pinned = { scale: MAX_SCALE, tx: 10, ty: 20 };
    expect(zoomAt(pinned, 2, 100, 100)).toBe(pinned);
  });

  it("zoomAtCentre anchors on the middle of the viewport", () => {
    const view = { scale: 1, tx: 0, ty: 0 };
    const viewport = { width: 800, height: 400 };
    const next = zoomAtCentre(view, 2, viewport);
    expect(next.scale).toBeCloseTo(2, 6);
    // The world point at the centre must not move.
    const before = screenToWorld(view, 400, 200);
    const after = screenToWorld(next, 400, 200);
    expect(after.x).toBeCloseTo(before.x, 6);
    expect(after.y).toBeCloseTo(before.y, 6);
  });
});

describe("fitToViewport", () => {
  it("scales a graph that is wider than the viewport and centres it", () => {
    const view = fitToViewport({ width: 2000, height: 500 }, { width: 1000, height: 600 }, 0);
    expect(view.scale).toBeCloseTo(0.5, 6);
    expect(view.tx).toBeCloseTo(0, 6);
    // 500 * 0.5 = 250 tall inside 600 -> 175px of padding top and bottom.
    expect(view.ty).toBeCloseTo(175, 6);
  });

  it("never magnifies a small graph past 1:1", () => {
    const view = fitToViewport({ width: 200, height: 100 }, { width: 1000, height: 600 }, 0);
    expect(view.scale).toBe(1);
    expect(view.tx).toBeCloseTo(400, 6);
    expect(view.ty).toBeCloseTo(250, 6);
  });

  it("honours the padding", () => {
    const padded = fitToViewport({ width: 1000, height: 1000 }, { width: 600, height: 600 }, 50);
    expect(padded.scale).toBeCloseTo(0.5, 6);
  });

  it("returns the identity viewport for empty content or an unmeasured container", () => {
    expect(fitToViewport({ width: 0, height: 0 }, { width: 800, height: 600 })).toBe(
      IDENTITY_VIEWPORT,
    );
    expect(fitToViewport({ width: 800, height: 600 }, { width: 0, height: 0 })).toBe(
      IDENTITY_VIEWPORT,
    );
  });

  it("never fits below the minimum scale", () => {
    const view = fitToViewport({ width: 100000, height: 100 }, { width: 500, height: 500 }, 0);
    expect(view.scale).toBe(MIN_SCALE);
  });
});

describe("zoomPercent", () => {
  it("rounds to whole percent", () => {
    expect(zoomPercent({ scale: 0.835, tx: 0, ty: 0 })).toBe(84);
    expect(zoomPercent(IDENTITY_VIEWPORT)).toBe(100);
  });
});
