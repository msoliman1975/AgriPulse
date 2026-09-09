import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import yaml from "js-yaml";
import { describe, expect, it } from "vitest";

import { ALLOWED_PROPS, FEATURES, FLOWS, TAXONOMY_VERSION } from "./taxonomy.generated";

/**
 * `taxonomy.generated.ts` is written by
 * `python backend/scripts/gen_telemetry_taxonomy.py` from the backend YAML.
 * Generated code that nothing checks rots, and the failure mode here is
 * expensive: the client would emit an event name the server rejects, and the
 * only symptom is a chart that stays empty.
 */

// cwd is the frontend package root; the YAML lives in the backend package.
const YAML_PATH = resolve(process.cwd(), "../backend/app/modules/telemetry/taxonomy.yaml");

interface RawTaxonomy {
  version: number;
  events: Record<string, { props?: string[] }>;
  features: string[];
  flows: Record<string, { timeout_minutes: number; steps: string[] }>;
}

function loadYaml(): RawTaxonomy {
  return yaml.load(readFileSync(YAML_PATH, "utf-8")) as RawTaxonomy;
}

describe("generated taxonomy", () => {
  const raw = loadYaml();

  it("has the same schema version as the server", () => {
    expect(TAXONOMY_VERSION).toBe(raw.version);
  });

  it("has the same event names", () => {
    expect(Object.keys(ALLOWED_PROPS).sort()).toEqual(Object.keys(raw.events).sort());
  });

  it("has the same props allow-list per event", () => {
    for (const [name, spec] of Object.entries(raw.events)) {
      expect([...ALLOWED_PROPS[name as keyof typeof ALLOWED_PROPS]].sort()).toEqual(
        [...(spec.props ?? [])].sort(),
      );
    }
  });

  it("has the same feature enum", () => {
    expect([...FEATURES].sort()).toEqual([...raw.features].sort());
  });

  it("has the same flows, steps and timeouts", () => {
    expect(Object.keys(FLOWS).sort()).toEqual(Object.keys(raw.flows).sort());
    for (const [name, spec] of Object.entries(raw.flows)) {
      const generated = FLOWS[name as keyof typeof FLOWS];
      expect(generated.timeoutMinutes).toBe(spec.timeout_minutes);
      expect([...generated.steps]).toEqual(spec.steps);
    }
  });
});
