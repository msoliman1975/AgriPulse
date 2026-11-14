// D20: an activity's catalogue input and structured dose. Moved from the old
// plan template editor (retired in Agri Operation PR 10) unchanged.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { DOSE_UNITS, type DoseUnit, type Input } from "@/api/inputs";
import type { ActivityInput } from "@/api/planTemplates";

export interface ActivityRow extends ActivityInput {
  key: string;
}

/**
 * D20: an input from the catalogue and a structured dose. Choosing an input
 * with one recommended dose offers it; the free-text product name stays for
 * context and is filled from the input when empty.
 */
export function ActivityInputFields({
  row,
  inputs,
  onChange,
}: {
  row: ActivityRow;
  inputs: Input[];
  onChange: (patch: Partial<ActivityRow>) => void;
}): ReactNode {
  const { t, i18n } = useTranslation("planTemplates");
  const ar = i18n.language.startsWith("ar");
  const num = (s: string): number | null => (s.trim() === "" ? null : Number(s));
  const pick = (id: string): void => {
    const input = inputs.find((i) => i.id === id);
    const only = input && input.doses.length === 1 ? input.doses[0] : undefined;
    onChange({
      input_id: id || null,
      product_name: row.product_name?.trim()
        ? row.product_name
        : (input?.name_en ?? row.product_name),
      ...(only && only.unit !== "other" && !row.dose_unit
        ? {
            dose_value:
              only.value != null
                ? Number(only.value)
                : only.value_min != null
                  ? Number(only.value_min)
                  : null,
            dose_value_max:
              only.value_max != null && only.value == null ? Number(only.value_max) : null,
            dose_unit: only.unit,
          }
        : {}),
    });
  };
  return (
    <>
      <select
        className="input w-44"
        aria-label={t("editor.field.input")}
        value={row.input_id ?? ""}
        onChange={(e) => pick(e.target.value)}
      >
        <option value="">{t("editor.field.noInput")}</option>
        {inputs.map((i) => (
          <option key={i.id} value={i.id}>
            {ar ? (i.name_ar ?? i.name_en) : i.name_en}
          </option>
        ))}
      </select>
      <input
        className="input w-16"
        inputMode="decimal"
        aria-label={t("editor.field.doseValue")}
        placeholder={t("editor.field.doseValue")}
        value={row.dose_value ?? ""}
        onChange={(e) => onChange({ dose_value: num(e.target.value) })}
      />
      <input
        className="input w-16"
        inputMode="decimal"
        aria-label={t("editor.field.doseMax")}
        placeholder={t("editor.field.doseMax")}
        value={row.dose_value_max ?? ""}
        onChange={(e) => onChange({ dose_value_max: num(e.target.value) })}
      />
      <select
        className="input w-28"
        aria-label={t("editor.field.doseUnit")}
        value={row.dose_unit ?? ""}
        onChange={(e) => onChange({ dose_unit: (e.target.value || null) as DoseUnit | null })}
      >
        <option value="">{t("editor.field.noUnit")}</option>
        {DOSE_UNITS.filter((u) => u !== "other").map((u) => (
          <option key={u} value={u}>
            {u}
          </option>
        ))}
      </select>
    </>
  );
}
