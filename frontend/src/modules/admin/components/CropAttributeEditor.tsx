import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { CropAttributeDefinitionCreate } from "@/api/cropCatalog";
import type {
  CropAttributeDefinition,
  CropAttributeGate,
  CropAttributeOption,
  CropAttributeValueType,
  CropVariety,
  CropVarietyStrain,
} from "@/api/crops";
import { Button } from "@/components/Button";
import { Field, FIELD_CONTROL_CLASS } from "@/components/Field";
import { FormFooter } from "@/components/FormFooter";

/** Mirrors `CropAttributeValueType` in the backend schemas. */
const VALUE_TYPES: CropAttributeValueType[] = [
  "integer",
  "decimal",
  "text",
  "boolean",
  "date",
  "single_select",
  "multi_select",
];

const NUMERIC_TYPES = new Set<CropAttributeValueType>(["integer", "decimal"]);
const SELECT_TYPES = new Set<CropAttributeValueType>(["single_select", "multi_select"]);

/**
 * Types a gate may point at, mirroring `GATEABLE_VALUE_TYPES` on the server.
 *
 * A gate on free text or a number would be an equality test no author can
 * reason about from the form, so the server refuses it — offering those as
 * gate targets here would just produce a 422 on save.
 */
const GATEABLE_TYPES = new Set<CropAttributeValueType>(["single_select", "boolean"]);

/**
 * Codes an attribute may not claim — `RESERVED_ATTRIBUTE_CODES` on the server.
 *
 * These already exist as `block_crops` columns or as decision-tree `block`
 * fields. Reusing one puts two identically-labelled entries in the condition
 * builder, one of which is always empty, with nothing anywhere to flag it.
 * The server rejects them; this list turns that into inline feedback instead
 * of a failed save.
 */
const RESERVED_CODES = new Set([
  "season_label",
  "planting_date",
  "actual_harvest_date",
  "canopy_size_class",
  "growth_stage",
  "is_current",
  "status",
  "notes",
  "crop_path",
  "crop_category",
  "crop_strain",
  "soil_texture",
  "salinity_class",
]);

const CODE_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/;

export interface EditorDraft extends CropAttributeDefinitionCreate {
  options: CropAttributeOption[];
}

export function emptyDraft(): EditorDraft {
  return {
    code: "",
    name_en: "",
    name_ar: "",
    value_type: "text",
    options: [],
    is_required: false,
    sort_order: 0,
    is_reportable: true,
  };
}

export function draftFrom(definition: CropAttributeDefinition): EditorDraft {
  return {
    crop_variety_id: definition.crop_variety_id,
    crop_variety_strain_id: definition.crop_variety_strain_id,
    code: definition.code,
    name_en: definition.name_en,
    name_ar: definition.name_ar,
    description_en: definition.description_en,
    description_ar: definition.description_ar,
    value_type: definition.value_type,
    unit_en: definition.unit_en,
    unit_ar: definition.unit_ar,
    value_min: definition.value_min,
    value_max: definition.value_max,
    decimal_places: definition.decimal_places,
    text_max_length: definition.text_max_length,
    options: definition.options ?? [],
    is_required: definition.is_required,
    required_when: definition.required_when,
    show_when: definition.show_when,
    group_code: definition.group_code,
    group_name_en: definition.group_name_en,
    group_name_ar: definition.group_name_ar,
    sort_order: definition.sort_order,
    is_reportable: definition.is_reportable,
  };
}

interface Props {
  draft: EditorDraft;
  onChange: (draft: EditorDraft) => void;
  /** Editing an existing definition: code + attachment become immutable. */
  isEdit: boolean;
  /** Sibling definitions at this crop — the candidates a gate can point at. */
  siblings: CropAttributeDefinition[];
  varieties: CropVariety[];
  strains: CropVarietyStrain[];
  onVarietyChange: (varietyId: string | null) => void;
  saving: boolean;
  error: string | null;
  onSubmit: () => void;
  onCancel: () => void;
}

/** Validation the server would apply, surfaced inline. */
export function draftErrors(draft: EditorDraft, t: (k: string) => string): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!CODE_RE.test(draft.code)) errors.code = t("cropAttrs.err.code");
  else if (RESERVED_CODES.has(draft.code)) errors.code = t("cropAttrs.err.reserved");
  if (!draft.name_en.trim()) errors.name_en = t("cropAttrs.err.required");
  // Arabic is not optional by design: an EN-only label renders as English
  // inside an otherwise-Arabic form, which is exactly what the paired
  // name_en/name_ar columns exist to prevent.
  if (!draft.name_ar.trim()) errors.name_ar = t("cropAttrs.err.required");
  if (SELECT_TYPES.has(draft.value_type) && draft.options.length === 0) {
    errors.options = t("cropAttrs.err.needOptions");
  }
  for (const option of draft.options) {
    if (!CODE_RE.test(option.code)) errors.options = t("cropAttrs.err.optionCode");
    else if (!option.name_en.trim() || !option.name_ar.trim()) {
      errors.options = t("cropAttrs.err.optionNames");
    }
  }
  if (
    draft.value_min != null &&
    draft.value_max != null &&
    Number(draft.value_min) > Number(draft.value_max)
  ) {
    errors.value_min = t("cropAttrs.err.range");
  }
  return errors;
}

export function CropAttributeEditor({
  draft,
  onChange,
  isEdit,
  siblings,
  varieties,
  strains,
  onVarietyChange,
  saving,
  error,
  onSubmit,
  onCancel,
}: Props): ReactNode {
  const { t } = useTranslation("admin");
  const [touched, setTouched] = useState(false);
  const errors = touched ? draftErrors(draft, t) : {};
  const set = (patch: Partial<EditorDraft>): void => onChange({ ...draft, ...patch });

  const gateTargets = siblings.filter(
    (s) => GATEABLE_TYPES.has(s.value_type) && s.code !== draft.code,
  );

  const gateRow = (which: "show_when" | "required_when", label: string): ReactNode => {
    const gate = draft[which] ?? null;
    const target = gateTargets.find((s) => s.code === gate?.code) ?? null;
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-ap-line p-3">
        <span className="text-xs font-semibold text-ap-ink">{label}</span>
        {gateTargets.length === 0 ? (
          <p className="text-xs text-ap-muted">{t("cropAttrs.noGateTargets")}</p>
        ) : (
          <>
            <select
              className={FIELD_CONTROL_CLASS}
              value={gate?.code ?? ""}
              onChange={(e) =>
                set({
                  [which]: e.target.value ? { code: e.target.value, in: [] } : null,
                })
              }
            >
              <option value="">{t("cropAttrs.gateNever")}</option>
              {gateTargets.map((s) => (
                <option key={s.id} value={s.code}>
                  {s.name_en} ({s.code})
                </option>
              ))}
            </select>
            {target ? (
              <div className="flex flex-col gap-1">
                <span className="text-[11px] text-ap-muted">{t("cropAttrs.gateWhenIn")}</span>
                {(target.value_type === "boolean"
                  ? [
                      { code: "true", label: t("cropAttrs.yes") },
                      { code: "false", label: t("cropAttrs.no") },
                    ]
                  : (target.options ?? []).map((o) => ({ code: o.code, label: o.name_en }))
                ).map((choice) => {
                  const raw: (string | boolean)[] = gate?.in ?? [];
                  const value: string | boolean =
                    target.value_type === "boolean" ? choice.code === "true" : choice.code;
                  const checked = raw.includes(value);
                  return (
                    <label key={choice.code} className="flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) => {
                          const next = e.target.checked
                            ? [...raw, value]
                            : raw.filter((v) => v !== value);
                          const updated: CropAttributeGate | null = next.length
                            ? { code: target.code, in: next }
                            : { code: target.code, in: [] };
                          set({ [which]: updated });
                        }}
                      />
                      <span>{choice.label}</span>
                    </label>
                  );
                })}
                {(gate?.in ?? []).length === 0 ? (
                  <span className="text-[11px] text-ap-crit">{t("cropAttrs.gateNeedsValue")}</span>
                ) : null}
              </div>
            ) : null}
          </>
        )}
      </div>
    );
  };

  return (
    <div className="flex flex-col">
      <div className="grid gap-3 p-4 sm:grid-cols-2">
        <Field label={t("cropAttrs.code")} error={errors.code} required>
          {(a11y) => (
            <input
              {...a11y}
              className={FIELD_CONTROL_CLASS}
              value={draft.code}
              disabled={isEdit}
              onChange={(e) => set({ code: e.target.value })}
            />
          )}
        </Field>
        <Field label={t("cropAttrs.valueType")} required>
          {(a11y) => (
            <select
              {...a11y}
              className={FIELD_CONTROL_CLASS}
              value={draft.value_type}
              disabled={isEdit}
              onChange={(e) => set({ value_type: e.target.value as CropAttributeValueType })}
            >
              {VALUE_TYPES.map((v) => (
                <option key={v} value={v}>
                  {t(`cropAttrs.type.${v}`)}
                </option>
              ))}
            </select>
          )}
        </Field>

        <Field label={t("cropAttrs.nameEn")} error={errors.name_en} required>
          {(a11y) => (
            <input
              {...a11y}
              className={FIELD_CONTROL_CLASS}
              value={draft.name_en}
              onChange={(e) => set({ name_en: e.target.value })}
            />
          )}
        </Field>
        <Field label={t("cropAttrs.nameAr")} error={errors.name_ar} required>
          {(a11y) => (
            <input
              {...a11y}
              dir="rtl"
              className={FIELD_CONTROL_CLASS}
              value={draft.name_ar}
              onChange={(e) => set({ name_ar: e.target.value })}
            />
          )}
        </Field>

        {!isEdit ? (
          <>
            <Field label={t("cropAttrs.variety")} help={t("cropAttrs.attachHelp")}>
              {(a11y) => (
                <select
                  {...a11y}
                  className={FIELD_CONTROL_CLASS}
                  value={draft.crop_variety_id ?? ""}
                  onChange={(e) => {
                    const id = e.target.value || null;
                    onVarietyChange(id);
                    set({ crop_variety_id: id, crop_variety_strain_id: null });
                  }}
                >
                  <option value="">{t("cropAttrs.wholeCrop")}</option>
                  {varieties.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name_en}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label={t("cropAttrs.strain")}>
              {(a11y) => (
                <select
                  {...a11y}
                  className={FIELD_CONTROL_CLASS}
                  value={draft.crop_variety_strain_id ?? ""}
                  disabled={!draft.crop_variety_id}
                  onChange={(e) => set({ crop_variety_strain_id: e.target.value || null })}
                >
                  <option value="">{t("cropAttrs.allStrains")}</option>
                  {strains.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name_en}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </>
        ) : null}

        {NUMERIC_TYPES.has(draft.value_type) ? (
          <>
            <Field label={t("cropAttrs.unitEn")}>
              {(a11y) => (
                <input
                  {...a11y}
                  className={FIELD_CONTROL_CLASS}
                  value={draft.unit_en ?? ""}
                  onChange={(e) => set({ unit_en: e.target.value || null })}
                />
              )}
            </Field>
            <Field label={t("cropAttrs.unitAr")}>
              {(a11y) => (
                <input
                  {...a11y}
                  dir="rtl"
                  className={FIELD_CONTROL_CLASS}
                  value={draft.unit_ar ?? ""}
                  onChange={(e) => set({ unit_ar: e.target.value || null })}
                />
              )}
            </Field>
            <Field label={t("cropAttrs.min")} error={errors.value_min}>
              {(a11y) => (
                <input
                  {...a11y}
                  type="number"
                  className={FIELD_CONTROL_CLASS}
                  value={draft.value_min ?? ""}
                  onChange={(e) => set({ value_min: e.target.value || null })}
                />
              )}
            </Field>
            <Field label={t("cropAttrs.max")}>
              {(a11y) => (
                <input
                  {...a11y}
                  type="number"
                  className={FIELD_CONTROL_CLASS}
                  value={draft.value_max ?? ""}
                  onChange={(e) => set({ value_max: e.target.value || null })}
                />
              )}
            </Field>
            {draft.value_type === "decimal" ? (
              <Field label={t("cropAttrs.decimals")}>
                {(a11y) => (
                  <input
                    {...a11y}
                    type="number"
                    min={0}
                    max={4}
                    className={FIELD_CONTROL_CLASS}
                    value={draft.decimal_places ?? ""}
                    onChange={(e) =>
                      set({ decimal_places: e.target.value === "" ? null : Number(e.target.value) })
                    }
                  />
                )}
              </Field>
            ) : null}
          </>
        ) : null}

        {draft.value_type === "text" ? (
          <Field label={t("cropAttrs.maxLength")}>
            {(a11y) => (
              <input
                {...a11y}
                type="number"
                min={1}
                max={4000}
                className={FIELD_CONTROL_CLASS}
                value={draft.text_max_length ?? ""}
                onChange={(e) =>
                  set({ text_max_length: e.target.value === "" ? null : Number(e.target.value) })
                }
              />
            )}
          </Field>
        ) : null}

        <Field label={t("cropAttrs.groupCode")} help={t("cropAttrs.groupHelp")}>
          {(a11y) => (
            <input
              {...a11y}
              className={FIELD_CONTROL_CLASS}
              value={draft.group_code ?? ""}
              onChange={(e) => set({ group_code: e.target.value || null })}
            />
          )}
        </Field>
        <Field label={t("cropAttrs.sortOrder")}>
          {(a11y) => (
            <input
              {...a11y}
              type="number"
              min={0}
              max={9999}
              className={FIELD_CONTROL_CLASS}
              value={draft.sort_order ?? 0}
              onChange={(e) => set({ sort_order: Number(e.target.value) })}
            />
          )}
        </Field>
        {draft.group_code ? (
          <>
            <Field label={t("cropAttrs.groupNameEn")}>
              {(a11y) => (
                <input
                  {...a11y}
                  className={FIELD_CONTROL_CLASS}
                  value={draft.group_name_en ?? ""}
                  onChange={(e) => set({ group_name_en: e.target.value || null })}
                />
              )}
            </Field>
            <Field label={t("cropAttrs.groupNameAr")}>
              {(a11y) => (
                <input
                  {...a11y}
                  dir="rtl"
                  className={FIELD_CONTROL_CLASS}
                  value={draft.group_name_ar ?? ""}
                  onChange={(e) => set({ group_name_ar: e.target.value || null })}
                />
              )}
            </Field>
          </>
        ) : null}
      </div>

      {SELECT_TYPES.has(draft.value_type) ? (
        <OptionsEditor
          options={draft.options}
          error={errors.options}
          onChange={(options) => set({ options })}
        />
      ) : null}

      <div className="grid gap-3 px-4 pb-4 sm:grid-cols-2">
        {gateRow("show_when", t("cropAttrs.showWhen"))}
        {gateRow("required_when", t("cropAttrs.requiredWhen"))}
      </div>

      <div className="flex flex-wrap gap-4 px-4 pb-4 text-sm">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.is_required ?? false}
            onChange={(e) => set({ is_required: e.target.checked })}
          />
          <span>{t("cropAttrs.alwaysRequired")}</span>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.is_reportable ?? true}
            onChange={(e) => set({ is_reportable: e.target.checked })}
          />
          <span>{t("cropAttrs.reportable")}</span>
        </label>
      </div>

      <FormFooter
        message={error}
        cancel={
          <Button variant="secondary" type="button" onClick={onCancel} disabled={saving}>
            {t("cropAttrs.cancel")}
          </Button>
        }
        submit={
          <Button
            type="button"
            disabled={saving}
            onClick={() => {
              setTouched(true);
              if (Object.keys(draftErrors(draft, t)).length === 0) onSubmit();
            }}
          >
            {saving ? t("cropAttrs.saving") : t("cropAttrs.save")}
          </Button>
        }
      />
    </div>
  );
}

function OptionsEditor({
  options,
  error,
  onChange,
}: {
  options: CropAttributeOption[];
  error?: string;
  onChange: (options: CropAttributeOption[]) => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  const patch = (index: number, next: Partial<CropAttributeOption>): void =>
    onChange(options.map((o, i) => (i === index ? { ...o, ...next } : o)));

  return (
    <div className="flex flex-col gap-2 px-4 pb-4">
      <span className="text-xs font-semibold text-ap-ink">{t("cropAttrs.options")}</span>
      {error ? <span className="text-xs text-ap-crit">{error}</span> : null}
      {options.map((option, index) => (
        <div key={index} className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
          <input
            className={FIELD_CONTROL_CLASS}
            placeholder={t("cropAttrs.optionCode")}
            value={option.code}
            onChange={(e) => patch(index, { code: e.target.value })}
          />
          <input
            className={FIELD_CONTROL_CLASS}
            placeholder={t("cropAttrs.nameEn")}
            value={option.name_en}
            onChange={(e) => patch(index, { name_en: e.target.value })}
          />
          <input
            className={FIELD_CONTROL_CLASS}
            dir="rtl"
            placeholder={t("cropAttrs.nameAr")}
            value={option.name_ar}
            onChange={(e) => patch(index, { name_ar: e.target.value })}
          />
          <Button
            variant="secondary"
            type="button"
            onClick={() => onChange(options.filter((_, i) => i !== index))}
          >
            {t("cropAttrs.removeOption")}
          </Button>
        </div>
      ))}
      <div>
        <Button
          variant="secondary"
          type="button"
          onClick={() =>
            onChange([
              ...options,
              { code: "", name_en: "", name_ar: "", sort_order: options.length },
            ])
          }
        >
          {t("cropAttrs.addOption")}
        </Button>
      </div>
    </div>
  );
}
