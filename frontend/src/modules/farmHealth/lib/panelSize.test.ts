// A remembered panel size: what is read back, and how often it is written.
//
// Both halves have failed silently in other places. A stored size outside
// the caller's range is applied whole and the handle then reports an
// `aria-valuenow` outside its own bounds; and a write per pointer move is
// invisible until someone drags a panel on a slow disk.

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { readSize, usePanelSize } from "./panelSize";

const KEY = "farmHealth.panel.rail";

beforeEach(() => {
  window.localStorage.clear();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("readSize", () => {
  it("returns the fallback when nothing is stored", () => {
    expect(readSize("rail", 308, 200, 560)).toBe(308);
  });

  it("returns what was stored", () => {
    window.localStorage.setItem(KEY, "420");

    expect(readSize("rail", 308, 200, 560)).toBe(420);
  });

  it("clamps a stored size into the caller's range", () => {
    // A size stored before the range changed, or by a different screen.
    window.localStorage.setItem(KEY, "5000");
    expect(readSize("rail", 308, 200, 560)).toBe(560);

    window.localStorage.setItem(KEY, "12");
    expect(readSize("rail", 308, 200, 560)).toBe(200);
  });

  it("treats a corrupt value as no value", () => {
    for (const stored of ["", "abc", "0", "-40", "NaN"]) {
      window.localStorage.setItem(KEY, stored);
      expect(readSize("rail", 308, 200, 560)).toBe(308);
    }
  });

  it("survives a browser that refuses storage entirely", () => {
    // A privacy window, or a browser set to block site data, throws on the
    // accessor itself rather than returning null.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("access denied");
    });

    expect(readSize("rail", 308, 200, 560)).toBe(308);
  });
});

describe("usePanelSize", () => {
  it("moves with every call and writes once the moves stop", () => {
    // A pointer fires 60 to 120 moves a second. Storing on each one was
    // that many synchronous writes per second of drag.
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { result } = renderHook(() => usePanelSize("rail", 308, 200, 560));

    act(() => {
      for (const size of [310, 320, 330, 340]) result.current[1](size);
    });

    // The panel followed the pointer the whole way.
    expect(result.current[0]).toBe(340);
    expect(setItem).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(400);
    });

    expect(setItem).toHaveBeenCalledTimes(1);
    expect(setItem).toHaveBeenCalledWith(KEY, "340");
  });

  it("stores the size a drag ended on even if the screen closes first", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const { result, unmount } = renderHook(() => usePanelSize("rail", 308, 200, 560));

    act(() => {
      result.current[1](420);
    });
    unmount();

    expect(setItem).toHaveBeenCalledWith(KEY, "420");
  });

  it("starts from the stored size, clamped", () => {
    window.localStorage.setItem(KEY, "9999");

    const { result } = renderHook(() => usePanelSize("rail", 308, 200, 560));

    expect(result.current[0]).toBe(560);
  });

  it("keeps working when the write is refused", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    const { result } = renderHook(() => usePanelSize("rail", 308, 200, 560));

    act(() => {
      result.current[1](420);
    });
    act(() => {
      vi.advanceTimersByTime(400);
    });

    expect(result.current[0]).toBe(420);
  });
});
