import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { PhenologyStagesEditor } from "@/modules/admin/components/PhenologyStagesEditor";
import { Link } from "react-router-dom";

import type { ClassificationDepth, Crop, CropVariety, CropVarietyStrain } from "@/api/crops";
import { isApiError } from "@/api/errors";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { FilterChip } from "@/components/FilterChip";
import { Field, FIELD_CONTROL_CLASS } from "@/components/Field";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Toolbar } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
import { useCapability } from "@/rbac/useCapability";
import {
  useAdminCrops,
  useAdminStrains,
  useAdminVarieties,
  useCreateCrop,
  useCreateStrain,
  useCreateVariety,
  useUpdateCrop,
  useUpdateStrain,
  useUpdateVariety,
} from "@/queries/cropCatalog";

const DEPTHS: ClassificationDepth[] = ["crop_only", "variety", "variety_strain"];
// Known categories already in the catalog, plus a couple of common extras.
// The form's category control is a dropdown of these with an "Other…"
// escape so a brand-new category can still be typed.
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

function apiMsg(err: unknown): string {
  return isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err);
}

/**
 * /platform/crops — PlatformAdmin authors the Crop → Variety → Strain
 * catalog. A lazy tree: each crop expands to its varieties (when its
 * classification_depth allows), each variety to its strains. Codes are
 * immutable (they anchor the canonical path); retire is a soft toggle.
 * PlatformSupport (platform.read but not manage) sees a read-only tree.
 */
export function PlatformCropsPage(): ReactNode {
  const { t } = useTranslation("admin");
  const canManage = useCapability("platform.manage_crops");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [adding, setAdding] = useState(false);
  const crops = useAdminCrops(includeInactive);

  return (
    <Page>
      <PageHeader
        title={t("crops.title")}
        subtitle={t("crops.subtitle")}
        badge={!canManage ? <Pill kind="warn">{t("crops.readonlyHint")}</Pill> : undefined}
        actions={
          canManage ? (
            <Button onClick={() => setAdding((v) => !v)}>{t("crops.addCrop")}</Button>
          ) : null
        }
      />

      <Toolbar
        chips={
          <FilterChip active={includeInactive} onToggle={() => setIncludeInactive((v) => !v)}>
            {t("crops.showRetired")}
          </FilterChip>
        }
      />

      {adding && canManage ? (
        <CropForm mode="create" onClose={() => setAdding(false)} onDone={() => setAdding(false)} />
      ) : null}

      <AsyncBoundary
        state={queryState(crops)}
        filtered={includeInactive}
        errorMessage={t("crops.loadFailed")}
        empty={
          <Card noPadding>
            <EmptyState
              message={t("crops.empty")}
              action={
                canManage ? (
                  <Button onClick={() => setAdding(true)}>{t("crops.addCrop")}</Button>
                ) : null
              }
            />
          </Card>
        }
      >
        {(rows) => (
          <Card noPadding>
            <div className="divide-y divide-ap-line">
              {rows.map((crop) => (
                <CropRow
                  key={crop.id}
                  crop={crop}
                  canManage={canManage}
                  includeInactive={includeInactive}
                />
              ))}
            </div>
          </Card>
        )}
      </AsyncBoundary>
    </Page>
  );
}

// ---- Crop row -------------------------------------------------------------

function CropRow({
  crop,
  canManage,
  includeInactive,
}: {
  crop: Crop;
  canManage: boolean;
  includeInactive: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [stagesOpen, setStagesOpen] = useState(false);
  const [addingVariety, setAddingVariety] = useState(false);
  const updateCrop = useUpdateCrop();

  const canHaveChildren = crop.classification_depth !== "crop_only";
  const varieties = useAdminVarieties(crop.id, includeInactive, open && canHaveChildren);

  return (
    <div className={crop.is_active ? "" : "opacity-60"}>
      <div className="flex items-center gap-2 px-4 py-2.5">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-start"
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? t("crops.collapse") : t("crops.expand")}
        >
          <span className="w-4 text-ap-muted">{open ? "▾" : "▸"}</span>
          <span className="min-w-0">
            <span className="font-medium text-ap-ink">{crop.name_en}</span>
            {crop.name_ar ? (
              <span className="ms-2 text-xs text-ap-muted">{crop.name_ar}</span>
            ) : null}
            <span className="ms-2 font-mono text-[11px] text-ap-primary">{crop.code}</span>
            <DepthBadge depth={crop.classification_depth} />
            {/* Most crops have no calendar, and nothing used to say so — a
                stage-gated tree simply never fired for them. */}
            {(crop.phenology_stages?.stages?.length ?? 0) > 0 ? (
              <span className="ms-2 rounded bg-ap-line/40 px-1.5 py-0.5 text-[11px] text-ap-muted">
                {crop.phenology_stages?.stages.length} {t("phenology.stages")}
              </span>
            ) : (
              <span className="ms-2 rounded bg-ap-warn/15 px-1.5 py-0.5 text-[11px] text-ap-warn">
                {t("phenology.noCalendar")}
              </span>
            )}
            {!crop.is_active ? <RetiredBadge /> : null}
          </span>
        </button>
        <Link
          to={`/platform/crops/${crop.id}/attributes`}
          className="text-xs font-medium text-ap-primary hover:underline"
        >
          {t("cropAttrs.manageLink")}
        </Link>
        {canManage ? (
          <button
            type="button"
            className="text-xs text-ap-primary hover:underline"
            onClick={() => setStagesOpen((v) => !v)}
          >
            {t("phenology.stages")}
          </button>
        ) : null}
        {canManage ? (
          <RowActions
            isActive={crop.is_active}
            onEdit={() => setEditing((v) => !v)}
            onToggle={() =>
              updateCrop.mutate({ cropId: crop.id, patch: { is_active: !crop.is_active } })
            }
            busy={updateCrop.isPending}
          />
        ) : null}
      </div>

      {stagesOpen && canManage ? (
        <div className="px-4 pb-3 ps-10">
          <PhenologyStagesEditor
            crop={crop}
            busy={updateCrop.isPending}
            onCancel={() => setStagesOpen(false)}
            onSave={(stages) =>
              updateCrop.mutate(
                { cropId: crop.id, patch: { phenology_stages: { stages } } },
                { onSuccess: () => setStagesOpen(false) },
              )
            }
          />
          {updateCrop.isError ? (
            <p role="alert" className="mt-1 text-[11px] text-ap-crit">
              {apiMsg(updateCrop.error)}
            </p>
          ) : null}
        </div>
      ) : null}

      {editing && canManage ? (
        <div className="px-4 pb-3 ps-10">
          <CropForm
            mode="edit"
            crop={crop}
            onClose={() => setEditing(false)}
            onDone={() => setEditing(false)}
          />
        </div>
      ) : null}

      {open && !canHaveChildren ? (
        <div className="border-t border-ap-line bg-ap-bg/30 px-4 py-2 ps-10 text-xs text-ap-muted">
          {t("crops.cropOnlyHint")}
          {canManage ? (
            <button
              className="ms-1 text-ap-primary hover:underline"
              onClick={() => setEditing(true)}
            >
              {t("crops.changeDepth")}
            </button>
          ) : null}
        </div>
      ) : null}

      {open && canHaveChildren ? (
        <div className="ps-10">
          {varieties.isLoading ? (
            <p className="px-4 py-2 text-xs text-ap-muted">{t("crops.loading")}</p>
          ) : (
            <div className="divide-y divide-ap-line border-t border-ap-line">
              {(varieties.data ?? []).length === 0 ? (
                <p className="px-4 py-2 text-xs text-ap-muted">{t("crops.noVarieties")}</p>
              ) : null}
              {(varieties.data ?? []).map((v) => (
                <VarietyRow
                  key={v.id}
                  crop={crop}
                  variety={v}
                  canManage={canManage}
                  includeInactive={includeInactive}
                />
              ))}
              {canManage ? (
                <div className="px-4 py-2">
                  {addingVariety ? (
                    <NodeForm
                      level="variety"
                      parentId={crop.id}
                      onClose={() => setAddingVariety(false)}
                    />
                  ) : (
                    <button
                      className="rounded border border-dashed border-ap-primary px-2 py-1 text-xs text-ap-primary hover:bg-ap-primary-soft"
                      onClick={() => setAddingVariety(true)}
                    >
                      + {t("crops.addVariety")}
                    </button>
                  )}
                </div>
              ) : null}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ---- Variety row ----------------------------------------------------------

function VarietyRow({
  crop,
  variety,
  canManage,
  includeInactive,
}: {
  crop: Crop;
  variety: CropVariety;
  canManage: boolean;
  includeInactive: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [addingStrain, setAddingStrain] = useState(false);
  const updateVariety = useUpdateVariety();

  const hasChildren = crop.classification_depth === "variety_strain";
  const strains = useAdminStrains(variety.id, includeInactive, open && hasChildren);

  return (
    <div className={variety.is_active ? "" : "opacity-60"}>
      <div className="flex items-center gap-2 px-4 py-2">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-2 text-start disabled:cursor-default"
          disabled={!hasChildren}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="w-4 text-ap-muted">{hasChildren ? (open ? "▾" : "▸") : ""}</span>
          <span className="min-w-0">
            <span className="text-sm text-ap-ink">{variety.name_en}</span>
            {variety.name_ar ? (
              <span className="ms-2 text-xs text-ap-muted">{variety.name_ar}</span>
            ) : null}
            <span className="ms-2 font-mono text-[11px] text-ap-primary">{variety.path}</span>
            {!variety.is_active ? <RetiredBadge /> : null}
          </span>
        </button>
        {canManage ? (
          <RowActions
            isActive={variety.is_active}
            onEdit={() => setEditing((v) => !v)}
            onToggle={() =>
              updateVariety.mutate({
                varietyId: variety.id,
                patch: { is_active: !variety.is_active },
              })
            }
            busy={updateVariety.isPending}
          />
        ) : null}
      </div>

      {editing && canManage ? (
        <div className="px-4 pb-2 ps-10">
          <NodeForm level="variety" node={variety} onClose={() => setEditing(false)} />
        </div>
      ) : null}

      {open && hasChildren ? (
        <div className="ps-10">
          {strains.isLoading ? (
            <p className="px-4 py-2 text-xs text-ap-muted">{t("crops.loading")}</p>
          ) : (
            <div className="divide-y divide-ap-line border-t border-ap-line">
              {(strains.data ?? []).length === 0 ? (
                <p className="px-4 py-2 text-xs text-ap-muted">{t("crops.noStrains")}</p>
              ) : null}
              {(strains.data ?? []).map((s) => (
                <StrainRow key={s.id} strain={s} canManage={canManage} />
              ))}
              {canManage ? (
                <div className="px-4 py-2">
                  {addingStrain ? (
                    <NodeForm
                      level="strain"
                      parentId={variety.id}
                      onClose={() => setAddingStrain(false)}
                    />
                  ) : (
                    <button
                      className="rounded border border-dashed border-ap-primary px-2 py-1 text-xs text-ap-primary hover:bg-ap-primary-soft"
                      onClick={() => setAddingStrain(true)}
                    >
                      + {t("crops.addStrain")}
                    </button>
                  )}
                </div>
              ) : null}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

// ---- Strain row -----------------------------------------------------------

function StrainRow({
  strain,
  canManage,
}: {
  strain: CropVarietyStrain;
  canManage: boolean;
}): ReactNode {
  const [editing, setEditing] = useState(false);
  const updateStrain = useUpdateStrain();
  return (
    <div className={strain.is_active ? "" : "opacity-60"}>
      <div className="flex items-center gap-2 px-4 py-2">
        <span className="w-4" />
        <div className="min-w-0 flex-1">
          <span className="text-sm text-ap-ink">{strain.name_en}</span>
          {strain.name_ar ? (
            <span className="ms-2 text-xs text-ap-muted">{strain.name_ar}</span>
          ) : null}
          <span className="ms-2 font-mono text-[11px] text-ap-primary">{strain.path}</span>
          {!strain.is_active ? <RetiredBadge /> : null}
        </div>
        {canManage ? (
          <RowActions
            isActive={strain.is_active}
            onEdit={() => setEditing((v) => !v)}
            onToggle={() =>
              updateStrain.mutate({ strainId: strain.id, patch: { is_active: !strain.is_active } })
            }
            busy={updateStrain.isPending}
          />
        ) : null}
      </div>
      {editing && canManage ? (
        <div className="px-4 pb-2 ps-10">
          <NodeForm level="strain" node={strain} onClose={() => setEditing(false)} />
        </div>
      ) : null}
    </div>
  );
}

// ---- Shared bits ----------------------------------------------------------

function DepthBadge({ depth }: { depth: ClassificationDepth }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <span className="ms-2 inline-flex items-center rounded bg-ap-bg px-1.5 py-0.5 text-[10px] text-ap-muted">
      {t(`crops.depth.${depth}`)}
    </span>
  );
}

function RetiredBadge(): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <span className="ms-2 inline-flex items-center rounded bg-ap-crit-soft px-1.5 py-0.5 text-[10px] text-ap-crit">
      {t("crops.retired")}
    </span>
  );
}

function RowActions({
  isActive,
  onEdit,
  onToggle,
  busy,
}: {
  isActive: boolean;
  onEdit: () => void;
  onToggle: () => void;
  busy: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <div className="flex flex-shrink-0 gap-2">
      <button className="text-xs text-ap-primary hover:underline" onClick={onEdit}>
        {t("crops.edit")}
      </button>
      <button
        className="text-xs text-ap-muted hover:underline disabled:opacity-50"
        disabled={busy}
        onClick={onToggle}
      >
        {isActive ? t("crops.retire") : t("crops.restore")}
      </button>
    </div>
  );
}

// ---- Crop form (create + edit) -------------------------------------------

function CropForm({
  mode,
  crop,
  onClose,
  onDone,
}: {
  mode: "create" | "edit";
  crop?: Crop;
  onClose: () => void;
  onDone: () => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  const createCrop = useCreateCrop();
  const updateCrop = useUpdateCrop();
  const [code, setCode] = useState(crop?.code ?? "");
  const [nameEn, setNameEn] = useState(crop?.name_en ?? "");
  const [nameAr, setNameAr] = useState(crop?.name_ar ?? "");
  const [category, setCategory] = useState(crop?.category ?? "cereal");
  // True when the crop's category isn't one of the known options, so the
  // dropdown shows "Other…" and reveals a free-text input.
  const [customCat, setCustomCat] = useState(crop ? !CATEGORIES.includes(crop.category) : false);
  const [depth, setDepth] = useState<ClassificationDepth>(
    crop?.classification_depth ?? "crop_only",
  );
  const [perennial, setPerennial] = useState(crop?.is_perennial ?? false);
  const [error, setError] = useState<string | null>(null);
  const busy = createCrop.isPending || updateCrop.isPending;

  const submit = (): void => {
    setError(null);
    const onError = (e: unknown): void => setError(apiMsg(e));
    if (mode === "create") {
      createCrop.mutate(
        {
          code: code.trim(),
          name_en: nameEn.trim(),
          name_ar: nameAr.trim(),
          category: category.trim(),
          is_perennial: perennial,
          classification_depth: depth,
        },
        { onSuccess: onDone, onError },
      );
    } else if (crop) {
      updateCrop.mutate(
        {
          cropId: crop.id,
          patch: {
            name_en: nameEn.trim(),
            name_ar: nameAr.trim(),
            category: category.trim(),
            is_perennial: perennial,
            classification_depth: depth,
          },
        },
        { onSuccess: onDone, onError },
      );
    }
  };

  return (
    <form
      className="mt-2 space-y-2 rounded-lg border border-ap-line bg-ap-bg/40 p-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Field label={t("crops.form.code")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              disabled={mode === "edit"}
              placeholder="mango"
              required
            />
          )}
        </Field>
        <Field label={t("crops.form.nameEn")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameEn}
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
              onChange={(e) => setNameAr(e.target.value)}
              required
              dir="rtl"
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
              {/* "Other" reveals a free-text box under the select; both belong
                  to the same field, so they share its label and wiring. */}
              {customCat ? (
                <input
                  className={`${FIELD_CONTROL_CLASS} mt-1`}
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder={t("crops.form.categoryCustom")}
                  aria-label={t("crops.form.categoryCustom")}
                  required
                />
              ) : null}
            </>
          )}
        </Field>
        <Field label={t("crops.form.depth")}>
          {(props) => (
            <select
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={depth}
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
        <label className="flex items-end gap-1.5 pb-2 text-xs text-ap-muted">
          <input
            type="checkbox"
            checked={perennial}
            onChange={(e) => setPerennial(e.target.checked)}
          />
          {t("crops.form.perennial")}
        </label>
      </div>
      {error ? <p className="text-xs text-ap-crit">{error}</p> : null}
      <FormButtons busy={busy} onCancel={onClose} />
    </form>
  );
}

// ---- Variety / strain form (create + edit) -------------------------------

function NodeForm({
  level,
  parentId,
  node,
  onClose,
}: {
  level: "variety" | "strain";
  parentId?: string;
  node?: CropVariety | CropVarietyStrain;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  const createVariety = useCreateVariety();
  const updateVariety = useUpdateVariety();
  const createStrain = useCreateStrain();
  const updateStrain = useUpdateStrain();
  const editing = Boolean(node);
  const [code, setCode] = useState(node?.code ?? "");
  const [nameEn, setNameEn] = useState(node?.name_en ?? "");
  const [nameAr, setNameAr] = useState(node?.name_ar ?? "");
  const [error, setError] = useState<string | null>(null);
  const busy =
    createVariety.isPending ||
    updateVariety.isPending ||
    createStrain.isPending ||
    updateStrain.isPending;

  const submit = (): void => {
    setError(null);
    const onError = (e: unknown): void => setError(apiMsg(e));
    const onSuccess = (): void => onClose();
    const createPayload = {
      code: code.trim(),
      name_en: nameEn.trim(),
      name_ar: nameAr.trim() || null,
    };
    const patch = { name_en: nameEn.trim(), name_ar: nameAr.trim() || null };
    if (level === "variety") {
      if (editing && node)
        updateVariety.mutate({ varietyId: node.id, patch }, { onSuccess, onError });
      else if (parentId)
        createVariety.mutate({ cropId: parentId, payload: createPayload }, { onSuccess, onError });
    } else {
      if (editing && node)
        updateStrain.mutate({ strainId: node.id, patch }, { onSuccess, onError });
      else if (parentId)
        createStrain.mutate(
          { varietyId: parentId, payload: createPayload },
          { onSuccess, onError },
        );
    }
  };

  return (
    <form
      className="space-y-2 rounded-lg border border-ap-line bg-ap-bg/40 p-2.5"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="grid grid-cols-3 gap-2">
        <Field label={t("crops.form.code")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              disabled={editing}
              required
            />
          )}
        </Field>
        <Field label={t("crops.form.nameEn")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nameEn}
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
              onChange={(e) => setNameAr(e.target.value)}
              dir="rtl"
            />
          )}
        </Field>
      </div>
      {error ? <p className="text-xs text-ap-crit">{error}</p> : null}
      <FormButtons busy={busy} onCancel={onClose} />
    </form>
  );
}

function FormButtons({ busy, onCancel }: { busy: boolean; onCancel: () => void }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <div className="flex gap-2">
      <Button type="submit" size="sm" disabled={busy}>
        {busy ? t("crops.form.saving") : t("crops.form.save")}
      </Button>
      <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
        {t("crops.form.cancel")}
      </Button>
    </div>
  );
}
