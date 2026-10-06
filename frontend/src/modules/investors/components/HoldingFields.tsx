import { useTranslation } from "react-i18next";

import type { HoldingWritableStatus } from "@/api/investors";
import { FIELD_CONTROL_CLASS, Field } from "@/components/Field";

export interface HoldingFieldValues {
  code: string;
  name: string;
  name_ar: string;
  /** Kept as text so an empty box means "unknown", not 0. */
  tree_count: string;
  status: HoldingWritableStatus;
  notes_internal: string;
}

interface Props {
  values: HoldingFieldValues;
  onChange: (values: HoldingFieldValues) => void;
  /** The code can be chosen on create only. */
  showCode?: boolean;
  /** A sold holding's stored status is not shown; "sold" is derived. */
  showStatus?: boolean;
}

/** The text fields of a holding, shared by the create and detail pages. */
export function HoldingFields({
  values,
  onChange,
  showCode = false,
  showStatus = true,
}: Props): JSX.Element {
  const { t } = useTranslation("investors");
  const set = <K extends keyof HoldingFieldValues>(key: K, value: HoldingFieldValues[K]) =>
    onChange({ ...values, [key]: value });

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {showCode ? (
        <Field label={t("holding.code")} help={t("holding.codeHelp")}>
          {(p) => (
            <input
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={values.code}
              maxLength={32}
              onChange={(e) => set("code", e.target.value)}
            />
          )}
        </Field>
      ) : null}
      <Field label={t("holding.name")} required>
        {(p) => (
          <input
            {...p}
            className={FIELD_CONTROL_CLASS}
            value={values.name}
            maxLength={200}
            required
            onChange={(e) => set("name", e.target.value)}
          />
        )}
      </Field>
      <Field label={t("holding.nameAr")}>
        {(p) => (
          <input
            {...p}
            dir="rtl"
            className={FIELD_CONTROL_CLASS}
            value={values.name_ar}
            maxLength={200}
            onChange={(e) => set("name_ar", e.target.value)}
          />
        )}
      </Field>
      <Field label={t("holding.trees")}>
        {(p) => (
          <input
            {...p}
            type="number"
            min={0}
            step={1}
            className={FIELD_CONTROL_CLASS}
            value={values.tree_count}
            onChange={(e) => set("tree_count", e.target.value)}
          />
        )}
      </Field>
      {showStatus ? (
        <Field label={t("holding.status")}>
          {(p) => (
            <select
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={values.status}
              onChange={(e) => set("status", e.target.value as HoldingWritableStatus)}
            >
              <option value="draft">{t("holdingStatus.draft")}</option>
              <option value="available">{t("holdingStatus.available")}</option>
            </select>
          )}
        </Field>
      ) : null}
      <Field label={t("holding.notes")} help={t("holding.notesHelp")} className="sm:col-span-2">
        {(p) => (
          <textarea
            {...p}
            rows={2}
            className={FIELD_CONTROL_CLASS}
            value={values.notes_internal}
            maxLength={4000}
            onChange={(e) => set("notes_internal", e.target.value)}
          />
        )}
      </Field>
    </div>
  );
}
