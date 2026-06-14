// In-place "Manage" sub-views for the Farm Console inspector. Replaces the
// v1 deep-links to legacy screens: edits happen natively here, reusing the
// existing crop-assign and grid-config cards + the blocks API.
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  getBlock,
  updateBlock,
  type BlockUpdatePayload,
  type IrrigationSource,
  type IrrigationSystem,
  type SalinityClass,
  type SoilTexture,
} from "@/api/blocks";
import { BlockCropAssignCard } from "../map/BlockCropAssignCard";
import { BlockGridConfigCard } from "@/modules/grid/BlockGridConfigCard";

export type ManageMode = "edit" | "crop" | "grid";

const IRR_SYSTEMS: IrrigationSystem[] = ["drip", "micro_sprinkler", "pivot", "furrow", "flood", "surface", "none"];
const IRR_SOURCES: IrrigationSource[] = ["well", "canal", "nile", "mixed"];
const SOIL_TEXTURES: SoilTexture[] = ["sandy", "sandy_loam", "loam", "clay_loam", "clay", "silty_loam", "silty_clay"];
const SALINITY: SalinityClass[] = ["non_saline", "slightly_saline", "moderately_saline", "strongly_saline"];

interface Props {
  mode: ManageMode;
  blockId: string;
  farmId: string;
  hasCurrentCrop: boolean;
  gridProductId: string | null;
  onDone: () => void; // return to monitor view + invalidate caches
}

export function ManagePanel({ mode, blockId, farmId, hasCurrentCrop, gridProductId, onDone }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  return (
    <div className="px-4 pb-8 pt-3">
      {mode === "edit" ? <EditForm blockId={blockId} onDone={onDone} /> : null}
      {mode === "crop" ? (
        <div className="rounded-xl border border-ap-line p-3">
          <BlockCropAssignCard blockId={blockId} farmId={farmId} hasCurrentCrop={hasCurrentCrop} onAssigned={onDone} />
        </div>
      ) : null}
      {mode === "grid" ? (
        gridProductId ? (
          <BlockGridConfigCard blockId={blockId} productId={gridProductId} />
        ) : (
          <div className="rounded-xl border border-ap-line p-4 text-sm text-ap-muted">
            {t("manage.noGridProduct")}
          </div>
        )
      ) : null}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }): ReactNode {
  return (
    <label className="mb-3 block">
      <span className="mb-1 block text-xs font-semibold text-ap-muted">{label}</span>
      {children}
    </label>
  );
}

const inputCls =
  "w-full rounded-lg border border-ap-line bg-ap-panel px-3 py-2 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";

function EditForm({ blockId, onDone }: { blockId: string; onDone: () => void }): ReactNode {
  const { t } = useTranslation("farmConsole");
  const qc = useQueryClient();
  const blockQ = useQuery({ queryKey: ["labs/mapnext/block", blockId], queryFn: () => getBlock(blockId), staleTime: 10_000 });

  const [form, setForm] = useState<BlockUpdatePayload | null>(null);
  const b = blockQ.data;
  // Seed the form once the block loads.
  const state: BlockUpdatePayload =
    form ??
    (b
      ? {
          name: b.name ?? null,
          irrigation_system: b.irrigation_system ?? null,
          irrigation_source: b.irrigation_source ?? null,
          soil_texture: b.soil_texture ?? null,
          salinity_class: b.salinity_class ?? null,
          soil_ph: b.soil_ph ?? null,
          notes: b.notes ?? null,
          tags: b.tags ?? [],
        }
      : {});
  const set = (patch: Partial<BlockUpdatePayload>) => setForm({ ...state, ...patch });

  const mut = useMutation({
    mutationFn: (patch: BlockUpdatePayload) => updateBlock(blockId, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/summary"] });
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/detail"] });
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/block", blockId] });
      onDone();
    },
  });

  if (blockQ.isLoading) return <div className="text-sm text-ap-muted">{t("inspector.loading")}</div>;
  if (blockQ.isError || !b) return <div className="text-sm text-ap-crit">{t("manage.editLoadError")}</div>;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mut.mutate(state);
      }}
    >
      <Field label={t("manage.name")}>
        <input className={inputCls} value={state.name ?? ""} onChange={(e) => set({ name: e.target.value || null })} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t("manage.irrSystem")}>
          <select className={inputCls} value={state.irrigation_system ?? ""} onChange={(e) => set({ irrigation_system: (e.target.value || null) as IrrigationSystem | null })}>
            <option value="">—</option>
            {IRR_SYSTEMS.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}
          </select>
        </Field>
        <Field label={t("manage.irrSource")}>
          <select className={inputCls} value={state.irrigation_source ?? ""} onChange={(e) => set({ irrigation_source: (e.target.value || null) as IrrigationSource | null })}>
            <option value="">—</option>
            {IRR_SOURCES.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </Field>
        <Field label={t("manage.soilTexture")}>
          <select className={inputCls} value={state.soil_texture ?? ""} onChange={(e) => set({ soil_texture: (e.target.value || null) as SoilTexture | null })}>
            <option value="">—</option>
            {SOIL_TEXTURES.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}
          </select>
        </Field>
        <Field label={t("manage.salinity")}>
          <select className={inputCls} value={state.salinity_class ?? ""} onChange={(e) => set({ salinity_class: (e.target.value || null) as SalinityClass | null })}>
            <option value="">—</option>
            {SALINITY.map((v) => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>)}
          </select>
        </Field>
      </div>
      <Field label={t("manage.soilPh")}>
        <input
          type="number"
          step="0.1"
          min={0}
          max={14}
          className={inputCls}
          value={state.soil_ph ?? ""}
          onChange={(e) => set({ soil_ph: e.target.value === "" ? null : Number(e.target.value) })}
        />
      </Field>
      <Field label={t("manage.tags")}>
        <input
          className={inputCls}
          value={(state.tags ?? []).join(", ")}
          onChange={(e) => set({ tags: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
        />
      </Field>
      <Field label={t("manage.notes")}>
        <textarea className={inputCls} rows={3} value={state.notes ?? ""} onChange={(e) => set({ notes: e.target.value || null })} />
      </Field>
      {mut.isError ? <div className="mb-2 text-xs text-ap-crit">{t("manage.saveError")}</div> : null}
      <div className="flex gap-2">
        <button type="submit" disabled={mut.isPending} className="h-9 flex-1 rounded-lg bg-ap-primary text-sm font-semibold text-white hover:bg-ap-primary/90 disabled:opacity-60">
          {mut.isPending ? t("manage.saving") : t("manage.save")}
        </button>
        <button type="button" onClick={onDone} className="h-9 rounded-lg border border-ap-line px-4 text-sm font-semibold text-ap-ink hover:bg-ap-bg/60">
          {t("manage.cancel")}
        </button>
      </div>
    </form>
  );
}
