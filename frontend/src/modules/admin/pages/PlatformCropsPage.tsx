import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ClassificationDepth, Crop, CropVariety, CropVarietyStrain } from "@/api/crops";
import { isApiError } from "@/api/errors";
import { Page } from "@/components/Page";
import { Skeleton } from "@/components/Skeleton";
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
  const { data, isLoading, isError } = useAdminCrops(includeInactive);

  return (
    <Page>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("crops.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("crops.subtitle")}</p>
          {!canManage ? (
            <p className="mt-2 text-xs text-ap-warn">{t("crops.readonlyHint")}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-ap-muted">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(e) => setIncludeInactive(e.target.checked)}
            />
            {t("crops.showRetired")}
          </label>
          {canManage ? (
            <button className="btn btn-primary" onClick={() => setAdding((v) => !v)}>
              {t("crops.addCrop")}
            </button>
          ) : null}
        </div>
      </header>

      {adding && canManage ? (
        <CropForm mode="create" onClose={() => setAdding(false)} onDone={() => setAdding(false)} />
      ) : null}

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : isError ? (
        <p className="text-sm text-ap-crit">{t("crops.loadFailed")}</p>
      ) : !data || data.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("crops.empty")}</p>
      ) : (
        <div className="divide-y divide-ap-line rounded-xl border border-ap-line bg-ap-panel">
          {data.map((crop) => (
            <CropRow
              key={crop.id}
              crop={crop}
              canManage={canManage}
              includeInactive={includeInactive}
            />
          ))}
        </div>
      )}
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
            {!crop.is_active ? <RetiredBadge /> : null}
          </span>
        </button>
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
          <input
            className="input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            disabled={mode === "edit"}
            placeholder="mango"
            required
          />
        </Field>
        <Field label={t("crops.form.nameEn")}>
          <input
            className="input"
            value={nameEn}
            onChange={(e) => setNameEn(e.target.value)}
            required
          />
        </Field>
        <Field label={t("crops.form.nameAr")}>
          <input
            className="input"
            value={nameAr}
            onChange={(e) => setNameAr(e.target.value)}
            required
            dir="rtl"
          />
        </Field>
        <Field label={t("crops.form.category")}>
          <select
            className="input"
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
          {customCat ? (
            <input
              className="input mt-1"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder={t("crops.form.categoryCustom")}
              required
            />
          ) : null}
        </Field>
        <Field label={t("crops.form.depth")}>
          <select
            className="input"
            value={depth}
            onChange={(e) => setDepth(e.target.value as ClassificationDepth)}
          >
            {DEPTHS.map((d) => (
              <option key={d} value={d}>
                {t(`crops.depth.${d}`)}
              </option>
            ))}
          </select>
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
          <input
            className="input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            disabled={editing}
            required
          />
        </Field>
        <Field label={t("crops.form.nameEn")}>
          <input
            className="input"
            value={nameEn}
            onChange={(e) => setNameEn(e.target.value)}
            required
          />
        </Field>
        <Field label={t("crops.form.nameAr")}>
          <input
            className="input"
            value={nameAr}
            onChange={(e) => setNameAr(e.target.value)}
            dir="rtl"
          />
        </Field>
      </div>
      {error ? <p className="text-xs text-ap-crit">{error}</p> : null}
      <FormButtons busy={busy} onCancel={onClose} />
    </form>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }): ReactNode {
  return (
    <label className="flex flex-col gap-0.5 text-[11px] text-ap-muted">
      {label}
      {children}
    </label>
  );
}

function FormButtons({ busy, onCancel }: { busy: boolean; onCancel: () => void }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <div className="flex gap-2">
      <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
        {busy ? t("crops.form.saving") : t("crops.form.save")}
      </button>
      <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel} disabled={busy}>
        {t("crops.form.cancel")}
      </button>
    </div>
  );
}
