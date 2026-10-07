import { render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";
import type { PolygonalFeature } from "@/lib/aoi/parse";
import { AoiUploader } from "./AoiUploader";

function square(name?: string): string {
  return JSON.stringify({
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: name ? { name } : {},
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [32.6, 30.07],
              [32.601, 30.07],
              [32.601, 30.071],
              [32.6, 30.071],
              [32.6, 30.07],
            ],
          ],
        },
      },
    ],
  });
}

function file(name: string, body: string): File {
  return new File([body], name, { type: "application/geo+json" });
}

describe("<AoiUploader multiple>", () => {
  beforeEach(async () => {
    await setupTestI18n();
  });

  it("joins the shapes of several files and names a nameless shape after its file", async () => {
    const onParsed = vi.fn<(f: PolygonalFeature[]) => void>();
    const { container } = render(<AoiUploader multiple onFeaturesParsed={onParsed} />);
    const input = container.querySelector<HTMLInputElement>("#aoi-file");
    expect(input?.multiple).toBe(true);

    await userEvent.upload(input as HTMLInputElement, [
      file("a.geojson", square("Named A")),
      file("holding_02.geojson", square()),
    ]);

    await waitFor(() => expect(onParsed).toHaveBeenCalledTimes(1));
    const names = onParsed.mock.calls[0][0].map(
      (f) => (f.properties as { name?: string } | null)?.name,
    );
    expect(names).toEqual(["Named A", "holding_02"]);
  });

  it("takes one file when multiple is off", () => {
    const { container } = render(<AoiUploader onFeaturesParsed={() => undefined} />);
    expect(container.querySelector<HTMLInputElement>("#aoi-file")?.multiple).toBe(false);
  });
});
