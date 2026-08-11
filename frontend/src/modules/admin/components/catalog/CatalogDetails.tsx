// The inspector's Details tab.
//
// A crop carries agronomic settings that the admin API has always accepted
// and no screen has ever rendered — the GDD temperatures above all, because a
// stage that advances on degree days is rejected outright without a base
// temperature, so one missing number quietly makes a whole advance mode
// unusable. The stage editor next door explains that; this is where it gets
// fixed.
//
// A variety or strain has no settings of its own beyond its names: everything
// else it can carry is an *override*, and those live on their own tabs where
// the inheritance can be shown.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { IndexCode } from "@/api/indices";
import type { ClassificationDepth, Crop, CropVariety, CropVarietyStrain } from "@/api/crops";
import { Button } from "@/components/Button";
import { Field, FIELD_CONTROL_CLASS } from "@/components/Field";
import { apiMsg } from "@/modules/admin/lib/apiMsg";
import { useUpdateCrop, useUpdateStrain, useUpdateVariety } from "@/queries/cropCatalog";

const DEPTHS: ClassificationDepth[] = ["crop_only", "variety", "variety_strain"];

const CATEGORIES = [
  "cereal",
  "fruit_tree",
  "vegetable",
  "legume",
  "oilseed",
  "fiber",
  "fodder",
  "sugar",
  "root_tuber",
  "herb",
];
const OTHER = "__other__";

// Exhaustive by construction: adding a code to `IndexCode` without listing it
// here is a type error, so this picker cannot silently fall behind the
// indices the platform actually computes.
const INDEX_LABELS: Record<IndexCode, string> = {
  ndvi: "NDVI",
  ndwi: "NDWI",
  evi: "EVI",
  savi: "SAVI",
  ndre: "NDRE",
  gndvi: "GNDVI",
  ndmi: "NDMI",
};
const INDEX_CODES = Object.keys(INDEX_LABELS) as IndexCode[];

/** A number input's value, kept as text so a half-typed "1." doesn't snap
 *  back to 1 under the cursor. `""` means "clear this field". */
function num(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export function CropDetailsForm({
  crop,
  canManage,
}: {
  crop: Crop;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const updateCrop = useUpdateCrop();
  // Keyed on the crop so switching nodes in the tree resets the form rather
  // than carrying the previous crop's edits across.
  const [nameEn, setNameEn] = useState(crop.name_en);
  const [nameAr, setNameAr] = useState(crop.name_ar);
  const [scientific, setScientific] = useState(crop.scientific_name ?? "");
  const [category, setCategory] = useState(crop.category);
  const [customCat, setCustomCat] = useState(!CATEGORIES.includes(crop.category));
  const [depth, setDepth] = useState<ClassificationDepth>(crop.classification_depth);
  const [perennial, setPerennial] = useState(crop.is_perennial);
  const [seasonDays, setSeasonDays] = useState(
    crop.default_growing_season_days == null ? "" : String(crop.default_growing_season_days),
  );
  const [gddBase, setGddBase] = useState(crop.gdd_base_temp_c ?? "");
  const [gddUpper, setGddUpper] = useState(crop.gdd_upper_temp_c ?? "");
  const [indices, setIndices] = useState<string[]>(crop.relevant_indices);
  const [saved, setSaved] = useState(false);

  const disabled = !canManage;

  const submit = (): void => {
    setSaved(false);
    updateCrop.mutate(
      {
        cropId: crop.id,
        patch: {
          name_en: nameEn.trim(),
          name_ar: nameAr.trim(),
          category: category.trim(),
          classification_depth: depth,
          is_perennial: perennial,
          scientific_name: scientific.trim() || null,
          default_growing_season_days: num(seasonDays),
          gdd_base_temp_c: num(gddBase),
          gdd_upper_temp_c: num(gddUpper),
          relevant_indices: indices,
        },
      },
      { onSuccess: () => setSaved(true) },
    );
  };

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <Locked label={t("crops.form.code")} value={crop.code} help={t("catalog.codeLocked")} />

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("crops.form.nameEn")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameEn}
              disabled={disabled}
              onChange={(e) => setNameEn(e.target.value)}
              required
            />
          )}
        </Field>
        <Field label={t("crops.form.nameAr")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameAr}
              dir="rtl"
              disabled={disabled}
              onChange={(e) => setNameAr(e.target.value)}
              required
            />
          )}
        </Field>
        <Field label={t("catalog.scientificName")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={scientific}
              disabled={disabled}
              placeholder="Mangifera indica"
              onChange={(e) => setScientific(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("crops.form.category")}>
          {(props) => (
            <>
              <select
                {...props}
                className={FIELD_CONTROL_CLASS}
                value={customCat ? OTHER : category}
                disabled={disabled}
                onChange={(e) => {
                  if (e.target.value === OTHER) {
                    setCustomCat(true);
                    setCategory("");
                  } else {
                    setCustomCat(false);
                    setCategory(e.target.value);
                  }
                }}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
                <option value={OTHER}>{t("crops.form.categoryOther")}</option>
              </select>
              {customCat ? (
                <input
                  className={`${FIELD_CONTROL_CLASS} mt-1`}
                  value={category}
                  disabled={disabled}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder={t("crops.form.categoryCustom")}
                  aria-label={t("crops.form.categoryCustom")}
                  required
                />
              ) : null}
            </>
          )}
        </Field>
        <Field label={t("crops.form.depth")} help={t("catalog.depthHint")}>
          {(props) => (
            <select
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={depth}
              disabled={disabled}
              onChange={(e) => setDepth(e.target.value as ClassificationDepth)}
            >
              {DEPTHS.map((d) => (
                <option key={d} value={d}>
                  {t(`crops.depth.${d}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("catalog.seasonDays")}>
          {(props) => (
            <input
              {...props}
              type="number"
              min={1}
              max={400}
              className={FIELD_CONTROL_CLASS}
              value={seasonDays}
              disabled={disabled}
              onChange={(e) => setSeasonDays(e.target.value)}
            />
          )}
        </Field>
      </div>

      <fieldset className="rounded-md border border-ap-line p-3">
        <legend className="px-1 text-xs font-medium text-ap-ink">{t("catalog.cycle")}</legend>
        <label className="flex items-center gap-2 text-xs text-ap-ink">
          <input
            type="checkbox"
            checked={perennial}
            disabled={disabled}
            onChange={(e) => setPerennial(e.target.checked)}
          />
          {t("crops.form.perennial")}
        </label>
        <p className="mt-1 text-[11px] text-ap-muted">
          {perennial ? t("phenology.perennialHint") : t("phenology.annualHint")}
        </p>

        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field label={t("catalog.gddBase")} help={t("catalog.gddBaseHint")}>
            {(props) => (
              <input
                {...props}
                type="number"
                step="0.1"
                min={0}
                max={40}
                className={FIELD_CONTROL_CLASS}
                value={gddBase}
                disabled={disabled || perennial}
                onChange={(e) => setGddBase(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("catalog.gddUpper")} help={t("catalog.gddUpperHint")}>
            {(props) => (
              <input
                {...props}
                type="number"
                step="0.1"
                min={0}
                max={60}
                className={FIELD_CONTROL_CLASS}
                value={gddUpper}
                disabled={disabled || perennial}
                onChange={(e) => setGddUpper(e.target.value)}
              />
            )}
          </Field>
        </div>
        {perennial ? (
          <p className="mt-1 text-[11px] text-ap-muted">{t("catalog.gddPerennialNote")}</p>
        ) : null}
      </fieldset>

      <fieldset className="rounded-md border border-ap-line p-3">
        <legend className="px-1 text-xs font-medium text-ap-ink">
          {t("catalog.relevantIndices")}
        </legend>
        <p className="mb-2 text-[11px] text-ap-muted">{t("catalog.relevantIndicesHint")}</p>
        <div className="flex flex-wrap gap-3">
          {INDEX_CODES.map((code) => (
            <label key={code} className="flex items-center gap-1.5 text-xs text-ap-ink">
              <input
                type="checkbox"
                checked={indices.includes(code)}
                disabled={disabled}
                onChange={(e) =>
                  setIndices((prev) =>
                    e.target.checked ? [...prev, code] : prev.filter((c) => c !== code),
                  )
                }
              />
              {INDEX_LABELS[code]}
            </label>
          ))}
        </div>
      </fieldset>

      {updateCrop.isError ? (
        <p role="alert" className="text-xs text-ap-crit">
          {apiMsg(updateCrop.error)}
        </p>
      ) : null}
      {saved && !updateCrop.isPending ? (
        <p role="status" className="text-xs text-ap-good">
          {t("catalog.saved")}
        </p>
      ) : null}

      {canManage ? (
        <Button type="submit" size="sm" disabled={updateCrop.isPending}>
          {updateCrop.isPending ? t("crops.form.saving") : t("crops.form.save")}
        </Button>
      ) : null}
    </form>
  );
}

export function NodeDetailsForm({
  node,
  level,
  canManage,
}: {
  node: CropVariety | CropVarietyStrain;
  level: "variety" | "strain";
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const updateVariety = useUpdateVariety();
  const updateStrain = useUpdateStrain();
  const [nameEn, setNameEn] = useState(node.name_en);
  const [nameAr, setNameAr] = useState(node.name_ar ?? "");
  const [saved, setSaved] = useState(false);

  const mutation = level === "variety" ? updateVariety : updateStrain;

  const submit = (): void => {
    setSaved(false);
    const patch = { name_en: nameEn.trim(), name_ar: nameAr.trim() || null };
    const opts = { onSuccess: () => setSaved(true) };
    if (level === "variety") updateVariety.mutate({ varietyId: node.id, patch }, opts);
    else updateStrain.mutate({ strainId: node.id, patch }, opts);
  };

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <Locked label={t("catalog.path")} value={node.path} help={t("catalog.codeLocked")} />

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("crops.form.nameEn")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameEn}
              disabled={!canManage}
              onChange={(e) => setNameEn(e.target.value)}
              required
            />
          )}
        </Field>
        <Field label={t("crops.form.nameAr")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameAr}
              dir="rtl"
              disabled={!canManage}
              onChange={(e) => setNameAr(e.target.value)}
            />
          )}
        </Field>
      </div>

      <p className="text-[11px] text-ap-muted">{t("catalog.nodeSettingsNote")}</p>

      {mutation.isError ? (
        <p role="alert" className="text-xs text-ap-crit">
          {apiMsg(mutation.error)}
        </p>
      ) : null}
      {saved && !mutation.isPending ? (
        <p role="status" className="text-xs text-ap-good">
          {t("catalog.saved")}
        </p>
      ) : null}

      {canManage ? (
        <Button type="submit" size="sm" disabled={mutation.isPending}>
          {mutation.isPending ? t("crops.form.saving") : t("crops.form.save")}
        </Button>
      ) : null}
    </form>
  );
}

/** A value that can never change after creation — shown, with the reason,
 *  rather than rendered as an input that silently refuses to be typed in. */
function Locked({ label, value, help }: { label: string; value: string; help: string }): ReactNode {
  return (
    <div>
      <p className="text-[11px] font-medium text-ap-muted">{label}</p>
      <p className="font-mono text-sm text-ap-ink">
        {value}
        <span className="ms-2 text-[11px] text-ap-muted">🔒 {help}</span>
      </p>
    </div>
  );
}
