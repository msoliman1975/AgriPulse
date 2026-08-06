// Pure helpers for the crop-attributes form.
//
// Mirrors `backend/app/modules/farms/crop_attributes.py` — specifically
// `gate_matches`, `is_visible` and `is_required`. The server is authoritative
// and re-validates every save; this exists so the form can hide and require
// fields as the user types without a round trip per keystroke.
//
// The one rule worth stating twice, because getting it backwards is silent:
// an absent `show_when` means **always shown**, an absent `required_when`
// means **never required**. Collapsing those two defaults into one makes
// every ungated field mandatory.

import type { CropAttributeDefinition, CropAttributeGate } from "@/api/crops";

/** Values keyed by definition code, as the form holds them. */
export type AttributeValues = Record<string, unknown>;

/** Evaluate one `{code, in: [...]}` / `{code, eq: ...}` gate.
 *
 *  Returns false for an absent gate — callers decide what absence means.
 *  Fails closed on an unanswered target: an unset establishment method must
 *  not reveal the transplant fields, or a half-filled form looks complete. */
export function gateMatches(gate: CropAttributeGate | null, values: AttributeValues): boolean {
  if (!gate?.code) return false;
  const actual = values[gate.code];
  if (actual === undefined || actual === null || actual === "") return false;
  if (gate.in !== undefined) {
    // A multi-select target matches when any selected option is listed.
    if (Array.isArray(actual)) return actual.some((v) => gate.in?.includes(v as string | boolean));
    return gate.in.includes(actual as string | boolean);
  }
  if (gate.eq !== undefined) return actual === gate.eq;
  return false;
}

export function isVisible(def: CropAttributeDefinition, values: AttributeValues): boolean {
  if (!def.show_when) return true;
  return gateMatches(def.show_when, values);
}

/** Only meaningful for a *visible* definition — a hidden field is never
 *  required, so callers must check {@link isVisible} first. */
export function isRequired(def: CropAttributeDefinition, values: AttributeValues): boolean {
  if (def.is_required) return true;
  return gateMatches(def.required_when ?? null, values);
}

export function visibleDefinitions(
  defs: CropAttributeDefinition[],
  values: AttributeValues,
): CropAttributeDefinition[] {
  return defs.filter((d) => isVisible(d, values));
}

function isBlank(value: unknown): boolean {
  if (value === undefined || value === null || value === "") return true;
  return Array.isArray(value) && value.length === 0;
}

/** Codes that are visible, required, and empty — the save blockers. */
export function missingRequired(
  defs: CropAttributeDefinition[],
  values: AttributeValues,
): string[] {
  return visibleDefinitions(defs, values)
    .filter((d) => isRequired(d, values) && isBlank(values[d.code]))
    .map((d) => d.code);
}

/** Codes whose gate has closed while still holding a value.
 *
 *  The server deletes these on save and records `cleared_by_gate`. Surfacing
 *  them lets the form warn *before* the save rather than leaving the user to
 *  notice a field vanished — switching establishment method back to Seed
 *  discards the transplant date, and that should not be a surprise. */
export function clearedByGate(defs: CropAttributeDefinition[], values: AttributeValues): string[] {
  const visible = new Set(visibleDefinitions(defs, values).map((d) => d.code));
  return defs.filter((d) => !visible.has(d.code) && !isBlank(values[d.code])).map((d) => d.code);
}

/** The PUT body: every visible field, plus an explicit null for anything the
 *  gate closed on. Sending the whole visible form (rather than a diff) matches
 *  the server's "one save per form" contract. */
export function buildPayload(
  defs: CropAttributeDefinition[],
  values: AttributeValues,
): Record<string, unknown> {
  const visible = new Set(visibleDefinitions(defs, values).map((d) => d.code));
  const payload: Record<string, unknown> = {};
  for (const def of defs) {
    const value = values[def.code];
    if (!visible.has(def.code)) {
      // Only mention it if there is something to clear; an untouched hidden
      // field would otherwise generate a no-op history entry.
      if (!isBlank(value)) payload[def.code] = null;
      continue;
    }
    payload[def.code] = isBlank(value) ? null : value;
  }
  return payload;
}

/** Group definitions by `group_code`, preserving server order within a group.
 *  Definitions with no group land in one trailing unnamed group. */
export function groupDefinitions(
  defs: CropAttributeDefinition[],
): {
  code: string;
  nameEn: string | null;
  nameAr: string | null;
  defs: CropAttributeDefinition[];
}[] {
  const groups: ReturnType<typeof groupDefinitions> = [];
  const index = new Map<string, number>();
  for (const def of defs) {
    const key = def.group_code ?? "";
    let at = index.get(key);
    if (at === undefined) {
      at = groups.length;
      index.set(key, at);
      groups.push({
        code: key,
        nameEn: def.group_name_en,
        nameAr: def.group_name_ar,
        defs: [],
      });
    }
    groups[at].defs.push(def);
  }
  return groups;
}

/** Localised label for a definition or option. The catalog is bilingual by
 *  construction, so this never falls back to a code. */
export function label(item: { name_en: string; name_ar: string | null }, language: string): string {
  return language.startsWith("ar") && item.name_ar ? item.name_ar : item.name_en;
}

/** Render a stored attribute value for display.
 *
 *  Handles the shapes the API actually returns: a multi-select arrives as a
 *  string array and a numeric as a decimal string. `String(value)` would turn
 *  the first into a bare comma-join and anything unexpected into
 *  `[object Object]`, so the cases are spelled out.
 *
 *  `options` maps option codes back to their localised label — a history entry
 *  reading "grafted_tree" is a code leaking into the UI. */
export function formatValue(
  value: unknown,
  def?: Pick<CropAttributeDefinition, "options">,
  language = "en",
): string {
  if (value === null || value === undefined || value === "") return "—";
  const optionLabel = (code: unknown): string => {
    const match = def?.options?.find((o) => o.code === code);
    return match ? label(match, language) : String(code);
  };
  if (Array.isArray(value)) return value.map(optionLabel).join(", ");
  if (typeof value === "boolean") return String(value);
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return optionLabel(value);
  return JSON.stringify(value);
}
