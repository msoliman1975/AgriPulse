import { describe, expect, it, vi } from "vitest";

import { handleBack, onBack } from "@/backStack";

describe("Android back stack", () => {
  it("does nothing with no layer open, so the app's own rule applies", () => {
    expect(handleBack()).toBe(false);
  });

  it("closes the newest layer only, once per press", () => {
    const photo = vi.fn();
    const outer = vi.fn();
    const offOuter = onBack(outer);
    const offPhoto = onBack(photo);
    expect(handleBack()).toBe(true);
    expect(photo).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
    offPhoto();
    expect(handleBack()).toBe(true);
    expect(outer).toHaveBeenCalledTimes(1);
    offOuter();
    expect(handleBack()).toBe(false);
  });

  it("removes only its own handler, even out of order", () => {
    const a = vi.fn();
    const b = vi.fn();
    const offA = onBack(a);
    const offB = onBack(b);
    offA();
    handleBack();
    expect(b).toHaveBeenCalledTimes(1);
    expect(a).not.toHaveBeenCalled();
    offB();
    offB();
    expect(handleBack()).toBe(false);
  });
});
