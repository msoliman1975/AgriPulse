import type { CustomFieldCells, CustomFieldDef, CustomFieldValue } from "@/api/reports";

/**
 * Rendering rules for tenant-defined report columns.
 *
 * Kept out of the report components because four of them render the same
 * cells: a crop attribute and a signal arrive in one envelope, and the only
 * thing that varies between reports is which table the column is bolted onto.
 *
 * The formatters return a plain string rather than a node so the CSV export
 * and the on-screen table cannot drift — an export that reads `0.145` where
 * the page reads `14.5%` is worse than no export.
 */

/** Localised column label. Signals have no Arabic name, so they fall back. */
export function fieldLabel(def: CustomFieldDef, language: string): string {
  const arabic = language.startsWith("ar");
  return (arabic ? def.name_ar : def.name_en) || def.name_en;
}

/** Localised unit symbol, or "" when the column is dimensionless. */
export function fieldUnit(def: CustomFieldDef, language: string): string {
  const arabic = language.startsWith("ar");
  return (arabic ? def.unit_ar : def.unit_en) || def.unit_en || "";
}

/** Label for one stored option code, falling back to the code itself.
 *
 * The fallback is the point: an option removed from the definition after a
 * value was recorded must still render as what was recorded, rather than as a
 * blank cell that reads like "nothing was entered". */
function optionLabel(def: CustomFieldDef, code: string, language: string): string {
  const option = def.options?.find((o) => o.code === code);
  if (!option) return code;
  const arabic = language.startsWith("ar");
  return (arabic ? option.name_ar : option.name_en) || option.name_en;
}

/**
 * One cell as text. Empty string when the block has no value — the caller
 * decides whether that shows as an em dash (table) or stays empty (CSV).
 *
 * Numbers keep the definition's `decimal_places` when it has one. Without it
 * the stored string passes through untouched, because rounding a value whose
 * precision nobody declared is a decision this layer has no basis to make.
 */
export function formatCustomValue(
  def: CustomFieldDef,
  value: CustomFieldValue | undefined,
  language: string,
): string {
  if (!value) return "";

  if (value.value_options && value.value_options.length > 0) {
    return value.value_options.map((code) => optionLabel(def, code, language)).join(", ");
  }
  if (value.value_boolean !== null) {
    return value.value_boolean ? "✓" : "✗";
  }
  if (value.value_date !== null) {
    return value.value_date;
  }
  if (value.value_numeric !== null) {
    const n = Number(value.value_numeric);
    if (!Number.isFinite(n)) return value.value_numeric;
    return def.decimal_places === null ? value.value_numeric : n.toFixed(def.decimal_places);
  }
  if (value.value_text !== null) {
    // A select stores a code; a free-text field stores what was typed. The
    // lookup returns the input unchanged when it is not an option code.
    return optionLabel(def, value.value_text, language);
  }
  return "";
}

/** Cell text plus the unit, for the table. `""` stays `""` — no bare unit. */
export function formatCustomCell(
  def: CustomFieldDef,
  cells: CustomFieldCells,
  language: string,
): string {
  const text = formatCustomValue(def, cells[def.key], language);
  if (!text) return "";
  const unit = fieldUnit(def, language);
  return unit ? `${text} ${unit}` : text;
}

/** True when the column's values should sit right-aligned in the table. */
export function isNumericField(def: CustomFieldDef): boolean {
  return (
    def.value_type === "integer" || def.value_type === "decimal" || def.value_type === "numeric"
  );
}

/**
 * The `fields` query param for a picked column list.
 *
 * `undefined` rather than `""` when nothing is picked: an empty string would
 * still land in the query key and in the URL, and the backend would parse it
 * to the same empty list — one more thing that has to agree for no benefit.
 */
export function fieldsParam(keys: readonly string[]): string | undefined {
  return keys.length > 0 ? keys.join(",") : undefined;
}

/** Column headers for the CSV export, matching `CustomHeaderCells`. */
export function customCsvHeaders(defs: CustomFieldDef[], language: string): string[] {
  return defs.map((def) => {
    const label = fieldLabel(def, language);
    // The unit rides in the header rather than in every cell: a CSV column of
    // "14.5 °Bx" is text, and text does not sum in a spreadsheet.
    const unit = language.startsWith("ar") ? def.unit_ar : def.unit_en;
    return unit ? `${label} (${unit})` : label;
  });
}

/** Cell values for the CSV export, in the same order as the headers. */
export function customCsvCells(
  defs: CustomFieldDef[],
  cells: CustomFieldCells,
  language: string,
): string[] {
  return defs.map((def) => formatCustomValue(def, cells[def.key], language));
}
