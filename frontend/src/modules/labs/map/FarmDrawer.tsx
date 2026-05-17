import { useState } from "react";

import type {
  FarmCreatePayload,
  FarmDetail,
  FarmType,
  FarmUpdatePayload,
  OwnershipType,
  WaterSource,
} from "@/api/farms";
import type { Block } from "@/api/blocks";
import type { MultiPolygon } from "geojson";

export type FarmDrawerMode = "create" | "view" | "edit";

interface Props {
  mode: FarmDrawerMode;
  // When mode is "view"/"edit", farm is the loaded FarmDetail.
  farm: FarmDetail | null;
  // Inactive blocks under this farm — surfaced in the Archive section
  // while editing/viewing an existing farm.
  inactiveBlocks: Block[];
  // Polygon coords (MultiPolygon) the user has just drawn — null while
  // no draw has happened. In create mode the form requires this to be
  // non-null before submit is enabled.
  draftBoundary: MultiPolygon | null;
  draftAreaM2: number | null;
  width: number;
  drawingAoi: boolean;
  submitting: boolean;
  submitError: string | null;
  onClose: () => void;
  onModeChange: (mode: FarmDrawerMode) => void;
  onStartDrawAoi: () => void;
  onCancelDrawAoi: () => void;
  onSubmitCreate: (payload: FarmCreatePayload) => void;
  onSubmitUpdate: (payload: FarmUpdatePayload) => void;
  onInactivateFarm: () => void;
  onReactivateBlock: (blockId: string) => void;
  onResizeMouseDown: (e: React.MouseEvent) => void;
}

const FARM_TYPES: FarmType[] = ["commercial", "research", "contract"];
const OWNERSHIPS: OwnershipType[] = ["owned", "leased", "partnership", "other"];
const WATER_SOURCES: WaterSource[] = ["well", "canal", "nile", "desalinated", "rainfed", "mixed"];

export function FarmDrawer({
  mode,
  farm,
  inactiveBlocks,
  draftBoundary,
  draftAreaM2,
  width,
  drawingAoi,
  submitting,
  submitError,
  onClose,
  onModeChange,
  onStartDrawAoi,
  onCancelDrawAoi,
  onSubmitCreate,
  onSubmitUpdate,
  onInactivateFarm,
  onReactivateBlock,
  onResizeMouseDown,
}: Props) {
  const editing = mode === "create" || mode === "edit";

  // Form state — seeded from the farm or empty for create.
  const [code, setCode] = useState(farm?.code ?? "");
  const [name, setName] = useState(farm?.name ?? "");
  const [description, setDescription] = useState(farm?.description ?? "");
  const [governorate, setGovernorate] = useState(farm?.governorate ?? "");
  const [district, setDistrict] = useState(farm?.district ?? "");
  const [nearestCity, setNearestCity] = useState(farm?.nearest_city ?? "");
  const [addressLine, setAddressLine] = useState(farm?.address_line ?? "");
  const [farmType, setFarmType] = useState<FarmType>(farm?.farm_type ?? "commercial");
  const [ownership, setOwnership] = useState<OwnershipType | "">(farm?.ownership_type ?? "");
  const [waterSource, setWaterSource] = useState<WaterSource | "">(
    farm?.primary_water_source ?? "",
  );
  const [establishedDate, setEstablishedDate] = useState<string>(farm?.established_date ?? "");
  const [tagsRaw, setTagsRaw] = useState(farm?.tags.join(", ") ?? "");
  const [activeFrom, setActiveFrom] = useState<string>(
    farm?.active_from ?? new Date().toISOString().slice(0, 10),
  );

  function buildPayload(): FarmCreatePayload | null {
    if (mode === "create" && !draftBoundary) return null;
    const tags = tagsRaw
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    return {
      code,
      name,
      description: description || null,
      boundary: draftBoundary as MultiPolygon,
      governorate: governorate || null,
      district: district || null,
      nearest_city: nearestCity || null,
      address_line: addressLine || null,
      farm_type: farmType,
      ownership_type: ownership === "" ? null : ownership,
      primary_water_source: waterSource === "" ? null : waterSource,
      established_date: establishedDate || null,
      tags,
      active_from: activeFrom || null,
    };
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (mode === "create") {
      const payload = buildPayload();
      if (!payload) return;
      onSubmitCreate(payload);
    } else if (mode === "edit") {
      // Only send changes that are actually filled. Boundary is sent
      // only if the user drew a fresh AOI in this edit.
      const update: FarmUpdatePayload = {
        name,
        description: description || null,
        governorate: governorate || null,
        district: district || null,
        nearest_city: nearestCity || null,
        address_line: addressLine || null,
        farm_type: farmType,
        ownership_type: ownership === "" ? null : ownership,
        primary_water_source: waterSource === "" ? null : waterSource,
        established_date: establishedDate || null,
        tags: tagsRaw
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      };
      if (draftBoundary) update.boundary = draftBoundary;
      onSubmitUpdate(update);
    }
  }

  const title = mode === "create" ? "New farm" : mode === "edit" ? "Edit farm" : "Farm details";

  return (
    <aside
      className="absolute right-0 top-0 z-20 h-full overflow-y-auto bg-white px-4 py-4 shadow-2xl"
      style={{ width }}
    >
      <ResizeHandle onMouseDown={onResizeMouseDown} />
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute right-2 top-2 rounded p-1 text-slate-500 hover:bg-slate-100"
      >
        ✕
      </button>

      <h2 className="text-[15px] font-medium text-slate-900">{title}</h2>
      {farm ? (
        <p className="text-[11px] text-slate-500">
          {farm.code} · {(farm.area_m2 / 10_000).toFixed(2)} ha ·{" "}
          {farm.is_active ? "Active" : `Inactive (since ${farm.active_to})`}
        </p>
      ) : null}

      {mode === "view" && farm ? (
        <button
          type="button"
          onClick={() => onModeChange("edit")}
          className="mt-3 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
        >
          Edit
        </button>
      ) : null}

      <form onSubmit={handleSubmit} className="mt-4 space-y-4">
        <Section title="Basic">
          <Field label="Code" required={mode === "create"}>
            <input
              type="text"
              value={code}
              disabled={!editing || mode === "edit"}
              onChange={(e) => setCode(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-[12px] disabled:bg-slate-50"
            />
          </Field>
          <Field label="Name" required>
            <input
              type="text"
              value={name}
              disabled={!editing}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-[12px] disabled:bg-slate-50"
            />
          </Field>
          <Field label="Description">
            <textarea
              value={description}
              disabled={!editing}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-[12px] disabled:bg-slate-50"
              rows={2}
            />
          </Field>
        </Section>

        <Section title="Location">
          <Field label="Governorate">
            <input
              type="text"
              value={governorate}
              disabled={!editing}
              onChange={(e) => setGovernorate(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-[12px] disabled:bg-slate-50"
            />
          </Field>
          <Field label="District">
            <input
              type="text"
              value={district}
              disabled={!editing}
              onChange={(e) => setDistrict(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-[12px] disabled:bg-slate-50"
            />
          </Field>
          <Field label="Nearest city">
            <input
              type="text"
              value={nearestCity}
              disabled={!editing}
              onChange={(e) => setNearestCity(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-[12px] disabled:bg-slate-50"
            />
          </Field>
          <Field label="Address">
            <input
              type="text"
              value={addressLine}
              disabled={!editing}
              onChange={(e) => setAddressLine(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-[12px] disabled:bg-slate-50"
            />
          </Field>
        </Section>

        <Section title="Operations">
          <Field label="Farm type">
            <select
              value={farmType}
              disabled={!editing}
              onChange={(e) => setFarmType(e.target.value as FarmType)}
              className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-[12px] disabled:bg-slate-50"
            >
              {FARM_TYPES.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Ownership">
            <select
              value={ownership}
              disabled={!editing}
              onChange={(e) => setOwnership(e.target.value as OwnershipType | "")}
              className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-[12px] disabled:bg-slate-50"
            >
              <option value="">—</option>
              {OWNERSHIPS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Water source">
            <select
              value={waterSource}
              disabled={!editing}
              onChange={(e) => setWaterSource(e.target.value as WaterSource | "")}
              className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-[12px] disabled:bg-slate-50"
            >
              <option value="">—</option>
              {WATER_SOURCES.map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Established">
            <input
              type="date"
              value={establishedDate}
              disabled={!editing}
              onChange={(e) => setEstablishedDate(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-[12px] disabled:bg-slate-50"
            />
          </Field>
          {mode === "create" ? (
            <Field label="Active from">
              <input
                type="date"
                value={activeFrom}
                onChange={(e) => setActiveFrom(e.target.value)}
                className="w-full rounded border border-slate-300 px-2 py-1 text-[12px]"
              />
            </Field>
          ) : null}
        </Section>

        <Section title="Tags">
          <Field label="Comma-separated">
            <input
              type="text"
              value={tagsRaw}
              disabled={!editing}
              onChange={(e) => setTagsRaw(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-[12px] disabled:bg-slate-50"
            />
          </Field>
        </Section>

        <Section title="AOI">
          {drawingAoi ? (
            <div className="rounded border border-amber-300 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-800">
              Draw the farm boundary on the map, then double-click to finish.
              <button
                type="button"
                onClick={onCancelDrawAoi}
                className="ms-2 rounded border border-amber-400 px-1.5 py-0.5 text-[10px]"
              >
                Cancel
              </button>
            </div>
          ) : draftBoundary ? (
            <p className="text-[11px] text-emerald-700">
              New boundary drawn · {((draftAreaM2 ?? 0) / 10_000).toFixed(2)} ha
            </p>
          ) : (
            <p className="text-[11px] text-slate-500">
              {farm ? `${(farm.area_m2 / 10_000).toFixed(2)} ha (existing).` : "No boundary yet."}
            </p>
          )}
          {editing && !drawingAoi ? (
            <button
              type="button"
              onClick={onStartDrawAoi}
              className="mt-1 rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
            >
              {draftBoundary ? "Re-draw AOI" : "Draw AOI on map"}
            </button>
          ) : null}
        </Section>

        {mode === "view" || mode === "edit" ? (
          <Section title={`Archive (${inactiveBlocks.length})`}>
            {inactiveBlocks.length === 0 ? (
              <p className="text-[11px] text-slate-500">No inactive blocks.</p>
            ) : (
              <ul className="divide-y divide-slate-100 text-[11px]">
                {inactiveBlocks.map((b) => (
                  <li key={b.id} className="flex items-center gap-2 py-1.5">
                    <span className="w-20 truncate text-slate-500">{b.code}</span>
                    <span className="flex-1 truncate text-slate-800">{b.name ?? ""}</span>
                    <span className="text-[10px] text-slate-500">since {b.active_to}</span>
                    <button
                      type="button"
                      onClick={() => onReactivateBlock(b.id)}
                      className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] hover:bg-slate-50"
                    >
                      Reactivate
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        ) : null}

        {submitError ? (
          <p className="rounded bg-red-50 px-2 py-1 text-[11px] text-red-700">{submitError}</p>
        ) : null}

        {editing ? (
          <div className="flex justify-between gap-2">
            {mode === "edit" ? (
              <button
                type="button"
                onClick={onInactivateFarm}
                className="rounded border border-red-300 px-2 py-1 text-[11px] text-red-700 hover:bg-red-50"
              >
                Inactivate farm…
              </button>
            ) : (
              <span />
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => (mode === "create" ? onClose() : onModeChange("view"))}
                disabled={submitting}
                className="rounded border border-slate-300 px-3 py-1 text-[12px] text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || (mode === "create" && !draftBoundary)}
                className="rounded bg-slate-900 px-3 py-1 text-[12px] font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {submitting ? "Saving…" : mode === "create" ? "Create farm" : "Save"}
              </button>
            </div>
          </div>
        ) : null}
      </form>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      <div className="space-y-2">{children}</div>
    </section>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-[11px]">
      <span className="text-slate-500">
        {label}
        {required ? <span className="text-red-700"> *</span> : null}
      </span>
      <div className="mt-0.5">{children}</div>
    </label>
  );
}

function ResizeHandle({ onMouseDown }: { onMouseDown: (e: React.MouseEvent) => void }) {
  return (
    // ARIA `separator` is the documented role for resize handles; the
    // mouse-down interaction is the whole point of the control. Keyboard
    // resize (arrow keys) would be the proper a11y completion but is a
    // feature, not a lint fix — suppress the false positive here.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize panel"
      onMouseDown={onMouseDown}
      className="absolute left-0 top-0 h-full w-1.5 cursor-col-resize select-none bg-transparent hover:bg-slate-200/70"
      style={{ touchAction: "none" }}
    />
  );
}
