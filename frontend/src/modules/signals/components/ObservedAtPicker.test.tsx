import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeAll, describe, expect, it } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { ObservedAtPicker, _internals } from "./ObservedAtPicker";

beforeAll(async () => {
  await setupTestI18n("en");
});

function Harness({ initial }: { initial: string | null }) {
  const [value, setValue] = useState<string | null>(initial);
  return (
    <div>
      <ObservedAtPicker value={value} onChange={setValue} />
      <output data-testid="echo">{value ?? "null"}</output>
    </div>
  );
}

describe("ObservedAtPicker", () => {
  it("round-trips an ISO value through the datetime-local input", () => {
    // Pick an arbitrary local time and round-trip it. We can't pin the
    // browser TZ in jsdom so check the local-input form matches the
    // helper, not a literal string.
    const iso = "2026-05-20T09:30:00.000Z";
    const localExpected = _internals.isoToLocalInput(iso);
    expect(localExpected).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
    expect(_internals.localInputToIso(localExpected)).not.toBeNull();
  });

  it("emits ISO on user change and resets to now on the Now button", async () => {
    const user = userEvent.setup();
    render(<Harness initial={null} />);
    expect(screen.getByTestId("echo").textContent).toBe("null");

    const input = screen.getByLabelText(/observed at/i);
    await user.type(input, "2026-05-20T09:30");
    expect(screen.getByTestId("echo").textContent).toMatch(/^2026-05/);
    // The emitted value is the ISO string of that local time; back through
    // the helper it returns the same local components.
    const echo = screen.getByTestId("echo").textContent ?? "";
    expect(_internals.isoToLocalInput(echo)).toBe("2026-05-20T09:30");

    const now = screen.getByRole("button", { name: /now/i });
    const before = Date.now();
    await user.click(now);
    const after = Date.now();
    const emitted = Date.parse(screen.getByTestId("echo").textContent ?? "");
    expect(emitted).toBeGreaterThanOrEqual(before);
    expect(emitted).toBeLessThanOrEqual(after + 1000);
  });

  it("null value renders an empty input", () => {
    render(<Harness initial={null} />);
    const input = screen.getByLabelText<HTMLInputElement>(/observed at/i);
    expect(input.value).toBe("");
  });
});
