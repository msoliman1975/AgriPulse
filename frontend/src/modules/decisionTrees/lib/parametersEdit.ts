// Pure-fn helpers for editing a tree's `parameters:` declaration block (PR-D3).
//
// Mirrors the per-node edit buffer pattern from `treeEdit.ts`: changes
// accumulate in a `ParametersEditBuffer` keyed by parameter name; on
// save, `applyParameterEditsToYaml` parses the source YAML, applies
// the patches in the parameters block, and dumps a new YAML string.
//
// The backend's loader (`compile_tree` + `_validate_parameters_block`)
// is the source of truth on schema; we mirror its validation here so
// the editor catches bad declarations before sending — bad declarations
// would otherwise crash the next sync_from_disk or fail the next
// authoring POST.
//
// Validation surface (mirrors backend):
//   * `type` ∈ number | integer | boolean | string | enum
//   * `default` is required
//   * `enum` types require non-empty `values` and `default` ∈ values
//   * number / integer with `min` / `max`: default must lie in range

import jsYaml from "js-yaml";

export type ParameterType = "number" | "integer" | "boolean" | "string" | "enum";

export interface ParameterDeclaration {
  type: ParameterType;
  default: unknown;
  description?: string | null;
  min?: number | null;
  max?: number | null;
  values?: unknown[] | null;
}

export type ParametersEditBuffer = {
  // null = delete-this-parameter; ParameterDeclaration = upsert
  [paramName: string]: ParameterDeclaration | null;
};

/** Returns true when the buffer has at least one pending change. */
export function hasParameterEdits(buf: ParametersEditBuffer): boolean {
  return Object.keys(buf).length > 0;
}

/** Strict validation of one declaration. Returns null if valid,
 *  else a short human-readable message. Mirrors `_validate_parameters_block`. */
export function validateParameterDeclaration(
  name: string,
  decl: ParameterDeclaration,
): string | null {
  if (!name || !/^[a-zA-Z0-9_]+$/.test(name)) {
    return "Name must be alphanumeric/underscore.";
  }
  if (!["number", "integer", "boolean", "string", "enum"].includes(decl.type)) {
    return `Unknown type ${decl.type}.`;
  }
  if (decl.default === undefined || decl.default === null) {
    return "Default is required.";
  }
  if (decl.type === "enum") {
    if (!Array.isArray(decl.values) || decl.values.length === 0) {
      return "Enum requires non-empty values.";
    }
    if (!decl.values.includes(decl.default)) {
      return "Default must be one of values.";
    }
  }
  if (decl.type === "number" || decl.type === "integer") {
    const def = decl.default;
    if (typeof def !== "number" || Number.isNaN(def)) {
      return "Default must be a number.";
    }
    if (decl.type === "integer" && !Number.isInteger(def)) {
      return "Default must be an integer.";
    }
    if (decl.min !== undefined && decl.min !== null && def < decl.min) {
      return `Default must be ≥ ${decl.min}.`;
    }
    if (decl.max !== undefined && decl.max !== null && def > decl.max) {
      return `Default must be ≤ ${decl.max}.`;
    }
  }
  if (decl.type === "boolean" && typeof decl.default !== "boolean") {
    return "Default must be a boolean.";
  }
  if (decl.type === "string" && typeof decl.default !== "string") {
    return "Default must be a string.";
  }
  return null;
}

interface ParsedYamlDoc {
  parameters?: Record<string, unknown>;
  [k: string]: unknown;
}

/** Apply the buffer to ``yaml`` and dump the result. Adds the
 *  ``parameters:`` block if it doesn't exist; removes it entirely if
 *  every parameter is being deleted. Patches that target a name
 *  unchanged by the buffer pass through unchanged. */
export function applyParameterEditsToYaml(
  yaml: string,
  buf: ParametersEditBuffer,
): string {
  if (!hasParameterEdits(buf)) return yaml;
  const loaded = jsYaml.load(yaml);
  const doc: ParsedYamlDoc =
    typeof loaded === "object" && loaded !== null
      ? (loaded as ParsedYamlDoc)
      : {};
  const existing: Record<string, unknown> =
    typeof doc.parameters === "object" && doc.parameters !== null
      ? { ...doc.parameters }
      : {};
  for (const [name, decl] of Object.entries(buf)) {
    if (decl === null) {
      delete existing[name];
    } else {
      // Strip undefined values so YAML dump produces clean output (no
      // ``null``s where the author left optional fields blank).
      const clean: Record<string, unknown> = { type: decl.type, default: decl.default };
      if (decl.description) clean.description = decl.description;
      if (decl.min !== undefined && decl.min !== null) clean.min = decl.min;
      if (decl.max !== undefined && decl.max !== null) clean.max = decl.max;
      if (decl.type === "enum" && decl.values && decl.values.length > 0) {
        clean.values = decl.values;
      }
      existing[name] = clean;
    }
  }
  if (Object.keys(existing).length === 0) {
    delete doc.parameters;
  } else {
    doc.parameters = existing;
  }
  return jsYaml.dump(doc, { sortKeys: false, lineWidth: 100, noRefs: true });
}
