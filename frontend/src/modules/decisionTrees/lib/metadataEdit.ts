// Read/write the tree-level name + description off a draft YAML body
// (experience redesign — metadata↔YAML sync).
//
// name_en / name_ar / description_en / description_ar are top-level keys
// in the tree YAML (the loader's compile_tree reads them). The metadata
// panel binds its name/description inputs to these via readTreeMeta +
// applyTreeMetaToYaml so the panel and the raw YAML text are two
// projections of the SAME draft — edit either, the other reflects it.
//
// Targeting (crop/country/soil/scope) is deliberately NOT handled here:
// the saved YAML doesn't reliably carry those keys, so targeting is
// edited against the DB row + persisted via PATCH, not the YAML round-trip.

import jsYaml from "js-yaml";

export interface TreeMetaFields {
  name_en: string;
  name_ar: string;
  description_en: string;
  description_ar: string;
}

interface ParsedMetaDoc {
  name_en?: unknown;
  name_ar?: unknown;
  description_en?: unknown;
  description_ar?: unknown;
  [k: string]: unknown;
}

const EMPTY: TreeMetaFields = {
  name_en: "",
  name_ar: "",
  description_en: "",
  description_ar: "",
};

const asString = (v: unknown): string => (typeof v === "string" ? v : "");

/** Pull the name/description fields out of a draft YAML body. Tolerant
 *  of an unparseable / non-object body — returns empties so the panel
 *  renders blank inputs rather than crashing. */
export function readTreeMeta(yaml: string | null): TreeMetaFields {
  if (!yaml) return { ...EMPTY };
  let doc: unknown;
  try {
    doc = jsYaml.load(yaml);
  } catch {
    return { ...EMPTY };
  }
  if (!doc || typeof doc !== "object") return { ...EMPTY };
  const d = doc as ParsedMetaDoc;
  return {
    name_en: asString(d.name_en),
    name_ar: asString(d.name_ar),
    description_en: asString(d.description_en),
    description_ar: asString(d.description_ar),
  };
}

/** Write the provided name/description fields back into the YAML and
 *  re-dump. Empty optional fields (name_ar / descriptions) are written
 *  as `null` so the loader treats them as absent; name_en is written
 *  verbatim (an empty name_en is left to compile-time validation to
 *  reject). Mirrors applyEditsToYaml's dump options so unedited regions
 *  keep their shape. */
export function applyTreeMetaToYaml(
  yaml: string,
  patch: Partial<TreeMetaFields>,
): string {
  let doc: unknown;
  try {
    doc = jsYaml.load(yaml);
  } catch {
    return yaml;
  }
  if (!doc || typeof doc !== "object") return yaml;
  const d = doc as ParsedMetaDoc;
  if (patch.name_en !== undefined) d.name_en = patch.name_en;
  if (patch.name_ar !== undefined) d.name_ar = patch.name_ar === "" ? null : patch.name_ar;
  if (patch.description_en !== undefined)
    d.description_en = patch.description_en === "" ? null : patch.description_en;
  if (patch.description_ar !== undefined)
    d.description_ar = patch.description_ar === "" ? null : patch.description_ar;
  return jsYaml.dump(d, { sortKeys: false, lineWidth: 100, noRefs: true });
}
