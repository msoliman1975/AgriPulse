import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { LocationCapture, type LocationValue } from "./LocationCapture";

beforeAll(async () => {
  await setupTestI18n("en");
});

afterEach(() => {
  // Reset any geolocation stub between tests.
  Reflect.deleteProperty(navigator, "geolocation");
});

function Harness({ blockId }: { blockId: string | null }) {
  const [value, setValue] = useState<LocationValue>({
    location_mode: "entity",
    location_point: null,
  });
  return (
    <div>
      <LocationCapture blockId={blockId} onChange={setValue} />
      <output data-testid="echo">{JSON.stringify(value)}</output>
    </div>
  );
}

function echo() {
  return JSON.parse(screen.getByTestId("echo").textContent ?? "{}") as LocationValue;
}

function stubGeolocation(impl: Partial<Geolocation>) {
  Object.defineProperty(navigator, "geolocation", {
    value: impl,
    configurable: true,
  });
}

describe("LocationCapture", () => {
  it("disables Point-in-block without a block and enables it with one", () => {
    const { rerender } = render(<Harness blockId={null} />);
    expect(screen.getByRole("radio", { name: /point in block/i })).toBeDisabled();
    rerender(<Harness blockId="block-1" />);
    expect(screen.getByRole("radio", { name: /point in block/i })).toBeEnabled();
  });

  it("reveals lat/lon on free_point and emits a point only when valid", async () => {
    const user = userEvent.setup();
    render(<Harness blockId={null} />);
    expect(echo().location_mode).toBe("entity");

    await user.click(screen.getByRole("radio", { name: /free point/i }));
    expect(echo().location_mode).toBe("free_point");
    expect(echo().location_point).toBeNull();

    await user.type(screen.getByLabelText(/latitude/i), "30.04");
    await user.type(screen.getByLabelText(/longitude/i), "31.23");
    expect(echo().location_point).toEqual({ latitude: 30.04, longitude: 31.23 });
  });

  it("rejects out-of-range coordinates (no point emitted)", async () => {
    const user = userEvent.setup();
    render(<Harness blockId={null} />);
    await user.click(screen.getByRole("radio", { name: /free point/i }));
    await user.type(screen.getByLabelText(/latitude/i), "200");
    await user.type(screen.getByLabelText(/longitude/i), "31");
    expect(echo().location_point).toBeNull();
    expect(screen.getByText(/valid latitude/i)).toBeInTheDocument();
  });

  it("fills lat/lon from the GPS button on success", async () => {
    const user = userEvent.setup();
    stubGeolocation({
      getCurrentPosition: ((success: PositionCallback) =>
        success({
          coords: { latitude: 25.5, longitude: 55.5 },
        } as GeolocationPosition)),
    });
    render(<Harness blockId={null} />);
    await user.click(screen.getByRole("radio", { name: /free point/i }));
    await user.click(screen.getByRole("button", { name: /use current location/i }));

    expect(screen.getByLabelText<HTMLInputElement>(/latitude/i).value).toBe("25.500000");
    expect(echo().location_point).toEqual({ latitude: 25.5, longitude: 55.5 });
  });

  it("shows an error when geolocation is denied", async () => {
    const user = userEvent.setup();
    stubGeolocation({
      getCurrentPosition: ((_s: PositionCallback, error: PositionErrorCallback) =>
        error({ code: 1, message: "denied" } as GeolocationPositionError)),
    });
    render(<Harness blockId={null} />);
    await user.click(screen.getByRole("radio", { name: /free point/i }));
    await user.click(screen.getByRole("button", { name: /use current location/i }));
    expect(screen.getByText(/couldn't get your location/i)).toBeInTheDocument();
  });
});
