import { describe, expect, it } from "vitest";

import { dumpBetaDoc, parseBetaDoc, readTargeting, writeTargeting } from "./betaTree";

// The Targeting tab edits these three keys of the definition. What must hold:
// an empty axis is "any" and disappears from the document; the legacy single
// `crop_path` counts as a crop and is folded away on write, or the compiler
// would merge it back in and a crop removed in the UI would return on save;
// everything else in the document is untouched.

const base = dumpBetaDoc({
  code: "t1",
  name_en: "T1",
  crop_path: "mango",
  root: "n_start",
  nodes: { n_start: { label_en: "start" } },
});

describe("beta targeting", () => {
  it("reads the legacy crop_path as a crop and normalises country codes", () => {
    const doc = parseBetaDoc(base);
    expect(readTargeting(doc)).toEqual({
      crop_paths: ["mango"],
      country_codes: [],
      soil_textures: [],
    });
    expect(
      readTargeting({
        crop_paths: ["citrus", "citrus"],
        country_codes: ["eg"],
        soil_textures: "clay",
      }),
    ).toEqual({ crop_paths: ["citrus"], country_codes: ["EG"], soil_textures: ["clay"] });
  });

  it("writes the three axes and drops the legacy crop_path", () => {
    const out = parseBetaDoc(
      writeTargeting(base, {
        crop_paths: ["citrus.valencia"],
        country_codes: ["EG", "JO"],
        soil_textures: ["clay", "loam"],
      }),
    );
    expect(out?.crop_path).toBeUndefined();
    expect(out?.crop_paths).toEqual(["citrus.valencia"]);
    expect(out?.country_codes).toEqual(["EG", "JO"]);
    expect(out?.soil_textures).toEqual(["clay", "loam"]);
    expect(out?.nodes).toEqual({ n_start: { label_en: "start" } });
    expect(out?.name_en).toBe("T1");
  });

  it("removes an empty axis so the tree reads as matching any", () => {
    const set = writeTargeting(base, {
      crop_paths: ["mango"],
      country_codes: ["EG"],
      soil_textures: [],
    });
    const cleared = parseBetaDoc(
      writeTargeting(set, { crop_paths: [], country_codes: [], soil_textures: [] }),
    );
    expect(cleared && "crop_paths" in cleared).toBe(false);
    expect(cleared && "country_codes" in cleared).toBe(false);
    expect(cleared && "soil_textures" in cleared).toBe(false);
    expect(readTargeting(cleared)).toEqual({
      crop_paths: [],
      country_codes: [],
      soil_textures: [],
    });
  });
});
