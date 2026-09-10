// The drag handle, driven the two ways a person drives it.
//
// The arithmetic is the part that can be wrong without anything throwing:
// a sign flipped under RTL, or a delta added to a stale prop instead of to
// the size the drag started from, both look like a handle that works and
// moves the wrong way or lags behind the pointer.
//
// jsdom implements neither `PointerEvent` nor pointer capture, and the gap
// is silent: without the class below, Testing Library falls back to a plain
// `Event`, so `button` and `clientX` arrive undefined and every drag in this
// file would pass through a component that never moved. `PointerEvent`
// extends `MouseEvent` in the specification, which is where the coordinates
// and the button come from, so that is what the stand-in extends.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { Resizer } from "./Resizer";

class TestPointerEvent extends MouseEvent {
  readonly pointerId: number;

  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 0;
  }
}

beforeAll(() => {
  (window as unknown as { PointerEvent: unknown }).PointerEvent = TestPointerEvent;
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn(() => true);
});

function drawVertical(props: Partial<Parameters<typeof Resizer>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <Resizer
      orientation="vertical"
      value={300}
      min={200}
      max={560}
      onChange={onChange}
      label="Block list width"
      {...props}
    />,
  );
  return { onChange, handle: screen.getByRole("separator") };
}

/** One drag, as the browser delivers it: down, move, up. */
function drag(handle: HTMLElement, from: number, to: number, axis: "x" | "y" = "x") {
  const at = (n: number) => (axis === "x" ? { clientX: n, clientY: 0 } : { clientX: 0, clientY: n });
  fireEvent.pointerDown(handle, { button: 0, pointerId: 1, ...at(from) });
  fireEvent.pointerMove(handle, { pointerId: 1, ...at(to) });
  fireEvent.pointerUp(handle, { pointerId: 1, ...at(to) });
}

describe("Resizer", () => {
  it("is a window splitter, and says what size it is", () => {
    const { handle } = drawVertical();

    expect(handle).toHaveAttribute("aria-orientation", "vertical");
    expect(handle).toHaveAttribute("aria-valuenow", "300");
    expect(handle).toHaveAttribute("aria-valuemin", "200");
    expect(handle).toHaveAttribute("aria-valuemax", "560");
    expect(handle).toHaveAccessibleName("Block list width");
    // Focusable, or a keyboard reader cannot reach it at all.
    expect(handle).toHaveAttribute("tabindex", "0");
  });

  it("follows the pointer by the distance it moved", () => {
    const { onChange, handle } = drawVertical();

    drag(handle, 400, 460);

    expect(onChange).toHaveBeenLastCalledWith(360);
  });

  it("measures every move from where the drag started, not from the last one", () => {
    // The prop is a render behind while a pointer is moving. Adding each
    // delta to it makes the panel crawl instead of following the pointer.
    const { onChange, handle } = drawVertical();

    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 400, clientY: 0 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 420, clientY: 0 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 440, clientY: 0 });

    expect(onChange.mock.calls.map((call) => call[0])).toEqual([320, 340]);
  });

  it("stops at the ends rather than reporting a size nobody asked for", () => {
    const { onChange, handle } = drawVertical();

    drag(handle, 400, 100);
    expect(onChange).toHaveBeenLastCalledWith(200);

    drag(handle, 400, 900);
    expect(onChange).toHaveBeenLastCalledWith(560);
  });

  it("does not start a drag on a secondary button", () => {
    // A right-click opens a menu and never delivers a pointerup here, so a
    // drag started by one would stick to the pointer.
    const { onChange, handle } = drawVertical();

    fireEvent.pointerDown(handle, { button: 2, pointerId: 1, clientX: 400, clientY: 0 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 460, clientY: 0 });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("ignores a move that is not part of a drag", () => {
    const { onChange, handle } = drawVertical();

    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 460, clientY: 0 });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("reverses when the panel it sizes is on the other side", () => {
    // Under RTL the block list sits at the right edge, so the drag that
    // widens it is the one going left.
    const { onChange, handle } = drawVertical({ reversed: true });

    drag(handle, 400, 460);

    expect(onChange).toHaveBeenLastCalledWith(240);
  });

  it("resizes from the keyboard, in the direction the key points", () => {
    const { onChange, handle } = drawVertical();

    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith(324);

    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith(276);

    fireEvent.keyDown(handle, { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith(200);

    fireEvent.keyDown(handle, { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith(560);
  });

  it("flips the keys too when it is reversed", () => {
    const { onChange, handle } = drawVertical({ reversed: true });

    fireEvent.keyDown(handle, { key: "ArrowRight" });

    expect(onChange).toHaveBeenLastCalledWith(276);
  });

  it("leaves keys it does not own to the page", () => {
    const { onChange, handle } = drawVertical();

    fireEvent.keyDown(handle, { key: "Tab" });
    fireEvent.keyDown(handle, { key: "ArrowUp" });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("drags up and down when it is a horizontal bar", () => {
    const onChange = vi.fn();
    render(
      <Resizer
        orientation="horizontal"
        value={380}
        min={180}
        max={900}
        onChange={onChange}
        label="Map height"
      />,
    );
    const handle = screen.getByRole("separator");
    expect(handle).toHaveAttribute("aria-orientation", "horizontal");

    drag(handle, 500, 560, "y");
    expect(onChange).toHaveBeenLastCalledWith(440);

    fireEvent.keyDown(handle, { key: "ArrowDown" });
    expect(onChange).toHaveBeenLastCalledWith(404);
  });
});
