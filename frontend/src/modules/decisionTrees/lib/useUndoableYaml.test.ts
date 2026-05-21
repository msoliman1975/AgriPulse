import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useUndoableYaml } from "./useUndoableYaml";

describe("useUndoableYaml", () => {
  it("starts on the initial value with no undo available", () => {
    const { result } = renderHook(() => useUndoableYaml("a"));
    expect(result.current.value).toBe("a");
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("pushes to history on setValue and undo walks back", () => {
    const { result } = renderHook(() => useUndoableYaml("a"));
    act(() => result.current.setValue("b"));
    act(() => result.current.setValue("c"));
    expect(result.current.value).toBe("c");
    expect(result.current.canUndo).toBe(true);
    act(() => result.current.undo());
    expect(result.current.value).toBe("b");
    act(() => result.current.undo());
    expect(result.current.value).toBe("a");
    expect(result.current.canUndo).toBe(false);
  });

  it("redo walks forward after undo", () => {
    const { result } = renderHook(() => useUndoableYaml("a"));
    act(() => result.current.setValue("b"));
    act(() => result.current.undo());
    expect(result.current.value).toBe("a");
    expect(result.current.canRedo).toBe(true);
    act(() => result.current.redo());
    expect(result.current.value).toBe("b");
  });

  it("truncates the redo branch on a new setValue", () => {
    const { result } = renderHook(() => useUndoableYaml("a"));
    act(() => result.current.setValue("b"));
    act(() => result.current.setValue("c"));
    act(() => result.current.undo()); // back at "b"
    act(() => result.current.setValue("d"));
    expect(result.current.value).toBe("d");
    expect(result.current.canRedo).toBe(false);
  });

  it("ignores no-op setValue calls", () => {
    const { result } = renderHook(() => useUndoableYaml("a"));
    act(() => result.current.setValue("a"));
    expect(result.current.canUndo).toBe(false);
  });

  it("replace resets history", () => {
    const { result } = renderHook(() => useUndoableYaml("a"));
    act(() => result.current.setValue("b"));
    act(() => result.current.setValue("c"));
    act(() => result.current.replace("z"));
    expect(result.current.value).toBe("z");
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });
});
