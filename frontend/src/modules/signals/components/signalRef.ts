import type { ValueKind } from "@/api/signals";

/**
 * The shape the backend conditions parser expects for a signal value
 * reference (see `app/shared/conditions/context.py` SIGNAL_KEYS +
 * `models.py` parser). `source` is the discriminator; `code` is the
 * SignalDefinition.code; `key` is the value column the predicate
 * resolves against.
 *
 * Out of scope here: ops, thresholds, the wrapping condition tree.
 * The author still authors the tree in the surrounding editor; this
 * component just emits the "leaf" ref.
 */
export interface SignalRef {
  source: "signals";
  code: string;
  key: ValueKey;
}

export type ValueKey = "value_numeric" | "value_categorical" | "value_event" | "value_boolean";

const KIND_TO_KEY: Record<ValueKind, ValueKey | null> = {
  numeric: "value_numeric",
  categorical: "value_categorical",
  event: "value_event",
  boolean: "value_boolean",
  // Geopoint signals exist (e.g. wildlife sightings) but aren't
  // predicateable — the engine can't compare a point against a
  // threshold. Caller renders "unsupported kind" instead.
  geopoint: null,
};

export function valueKeyForKind(kind: ValueKind): ValueKey | null {
  return KIND_TO_KEY[kind] ?? null;
}

export function buildSignalRef(code: string, key: ValueKey): SignalRef {
  return { source: "signals", code, key };
}

/**
 * JSON form for the tenant-rule editor (which authors conditions as
 * JSON). Indented to fit nicely inside a tree like:
 *   "left": { "source": "signals", "code": "soil_ph", "key": "value_numeric" }
 */
export function refToJson(ref: SignalRef): string {
  return JSON.stringify(ref);
}

/**
 * YAML inline-mapping form for the decision-tree editor (which
 * authors trees in YAML). Inline form pastes cleanly into both
 * key-value and list contexts:
 *   left: { source: signals, code: soil_ph, key: value_numeric }
 */
export function refToYaml(ref: SignalRef): string {
  return `{ source: ${ref.source}, code: ${ref.code}, key: ${ref.key} }`;
}
