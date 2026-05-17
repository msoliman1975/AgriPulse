import { useEffect, useState } from "react";

import type {
  Block,
  BlockUpdatePayload,
  IrrigationSource,
  IrrigationSystem,
  SalinityClass,
  SoilTexture,
} from "@/api/blocks";

import { IndexChart } from "./IndexChart";
import type { IndexCode, IntegrationKindStatus, UnitDetail } from "./types";

interface Props {
  detail: UnitDetail | null;
  isLoading: boolean;
  onClose: () => void;
  width: number;
  onResizeMouseDown: (e: React.MouseEvent) => void;
  onInactivate?: () => void;
  // Block-edit hooks. The parent owns the editable Block record (loaded
  // via getBlock when the user enters edit mode) and the reshape state.
  editableBlock?: Block | null;
  onStartEdit?: () => void;
  onCancelEdit?: () => void;
  onSaveEdit?: (patch: BlockUpdatePayload) => void;
  saving?: boolean;
  saveError?: string | null;
  // Reshape: parent tracks whether we are reshaping this block.
  reshaping?: boolean;
  onStartReshape?: () => void;
  onSaveReshape?: () => void;
  onCancelReshape?: () => void;
  reshapeSaving?: boolean;
}

const HEALTH_LABEL = {
  healthy: "Healthy",
  watch: "Watch",
  critical: "Critical",
  unknown: "Unknown",
} as const;

const HEALTH_BG = {
  healthy: "#eaf3de",
  watch: "#faeeda",
  critical: "#fcebeb",
  unknown: "#eeeeee",
} as const;

const HEALTH_TEXT = {
  healthy: "#173404",
  watch: "#412402",
  critical: "#501313",
  unknown: "#3a3a3a",
} as const;

export function DetailPanel({
  detail,
  isLoading,
  onClose,
  width,
  onResizeMouseDown,
  onInactivate,
  editableBlock,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  saving,
  saveError,
  reshaping,
  onStartReshape,
  onSaveReshape,
  onCancelReshape,
  reshapeSaving,
}: Props) {
  const [activeIndex, setActiveIndex] = useState<IndexCode | null>(null);
  const editing = Boolean(editableBlock);

  const baseClass =
    "absolute right-0 top-0 z-10 h-full overflow-y-auto bg-white px-4 py-4 shadow-xl";

  if (isLoading || !detail) {
    return (
      <aside className={baseClass} style={{ width }}>
        <ResizeHandle onMouseDown={onResizeMouseDown} />
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="absolute right-2 top-2 rounded p-1 text-slate-500 hover:bg-slate-100"
        >
          ✕
        </button>
        <p className="text-sm text-slate-500">Loading…</p>
      </aside>
    );
  }

  const updated = detail.last_updated ? formatRelative(detail.last_updated) : "—";

  const activitiesNext = detail.activities.filter((a) => a.phase === "next7d");
  const activitiesLater = detail.activities.filter((a) => a.phase === "later");

  return (
    <aside className={baseClass} style={{ width }}>
      <ResizeHandle onMouseDown={onResizeMouseDown} />
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute right-2 top-2 rounded p-1 text-slate-500 hover:bg-slate-100"
      >
        ✕
      </button>

      {detail.parent_pivot_id ? (
        <p className="text-[10px] uppercase tracking-wider text-slate-500">
          ↳ Pivot section · logical group not selectable
        </p>
      ) : null}
      <h2 className="text-[15px] font-medium text-slate-900">{detail.name}</h2>
      <p className="text-[11px] text-slate-500">
        {detail.type} · {detail.area_ha.toFixed(2)} ha
      </p>

      {!editing && !reshaping ? (
        <div className="mt-2 flex gap-2">
          {onStartEdit ? (
            <button
              type="button"
              onClick={onStartEdit}
              className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
            >
              Edit
            </button>
          ) : null}
          {onStartReshape ? (
            <button
              type="button"
              onClick={onStartReshape}
              className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50"
            >
              Reshape
            </button>
          ) : null}
        </div>
      ) : null}

      {reshaping ? (
        <div className="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-800">
          Drag vertices on the map to reshape · save to commit.
          <div className="mt-1 flex gap-2">
            <button
              type="button"
              onClick={onSaveReshape}
              disabled={reshapeSaving}
              className="rounded bg-slate-900 px-2 py-0.5 text-[11px] font-medium text-white disabled:opacity-50"
            >
              {reshapeSaving ? "Saving…" : "Save reshape"}
            </button>
            <button
              type="button"
              onClick={onCancelReshape}
              disabled={reshapeSaving}
              className="rounded border border-slate-300 px-2 py-0.5 text-[11px] text-slate-700"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {editing && editableBlock && onSaveEdit && onCancelEdit ? (
        <EditForm
          block={editableBlock}
          saving={!!saving}
          saveError={saveError ?? null}
          onCancel={onCancelEdit}
          onSubmit={onSaveEdit}
        />
      ) : null}

      <div
        className="mt-3 flex items-center justify-between rounded-md px-3 py-2 text-xs"
        style={{
          backgroundColor: HEALTH_BG[detail.health],
          color: HEALTH_TEXT[detail.health],
        }}
      >
        <span className="flex items-center gap-2">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ backgroundColor: HEALTH_TEXT[detail.health] }}
          />
          {HEALTH_LABEL[detail.health]}
        </span>
        <span className="text-[10px] opacity-80">Updated {updated}</span>
      </div>

      {detail.plan || detail.crop_assignment ? (
        <Section title="Plan">
          {detail.plan ? (
            <div className="mt-1 rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-[11px]">
              <div className="font-medium text-slate-800">{detail.plan.name ?? "Season plan"}</div>
              <div className="text-slate-500">
                {detail.plan.season_label} · {detail.plan.season_year} ·{" "}
                <span className="capitalize">{detail.plan.status}</span>
              </div>
            </div>
          ) : (
            <p className="mt-1 text-[11px] text-slate-500">No active season plan.</p>
          )}
          {detail.crop_assignment ? (
            <div className="mt-1 text-[11px] text-slate-700">
              <span className="font-medium text-slate-800">{detail.crop_assignment.crop_name}</span>
              {detail.crop_assignment.variety_name
                ? ` · ${detail.crop_assignment.variety_name}`
                : ""}
              <span className="text-slate-500">
                {" · "}
                {detail.crop_assignment.season_label}
              </span>
              {detail.crop_assignment.planting_date ? (
                <div className="text-[10px] text-slate-500">
                  Planted {detail.crop_assignment.planting_date}
                  {detail.crop_assignment.growth_stage
                    ? ` · stage: ${detail.crop_assignment.growth_stage}`
                    : ""}
                </div>
              ) : null}
            </div>
          ) : (
            <p className="mt-1 text-[11px] text-slate-500">No crop assigned.</p>
          )}
        </Section>
      ) : null}

      {detail.alerts.length > 0 ? (
        <Section title={`Alerts (${detail.alerts.length})`}>
          {detail.alerts.map((a) => (
            <div
              key={a.id}
              className="mt-1 rounded border-l-4 px-2 py-1 text-[11px]"
              style={{
                borderColor: a.severity === "critical" ? "#A32D2D" : "#854F0B",
                background: a.severity === "critical" ? "#fcebeb" : "#faeeda",
                color: a.severity === "critical" ? "#501313" : "#412402",
              }}
            >
              {a.message}
            </div>
          ))}
        </Section>
      ) : null}

      <Section title="Vegetation indices" hint="(last 7d) · click to expand">
        <div className="mt-1 grid grid-cols-3 gap-2">
          {(["ndvi", "ndre", "ndwi"] as IndexCode[]).map((code) => {
            const s = detail.indices[code];
            const isActive = activeIndex === code;
            return (
              <button
                key={code}
                type="button"
                onClick={() => setActiveIndex(isActive ? null : code)}
                className={`rounded-md border px-2 py-1.5 text-left transition ${
                  isActive
                    ? "border-slate-300 bg-slate-50"
                    : "border-slate-200 hover:border-slate-300"
                }`}
              >
                <div className="text-[10px] uppercase text-slate-500">{code}</div>
                <div className="text-[15px] font-medium text-slate-900">
                  {s.current != null ? s.current.toFixed(2) : "—"}
                </div>
                <Trend delta={s.trend_7d_delta} />
              </button>
            );
          })}
        </div>
        {activeIndex ? (
          <IndexChart code={activeIndex} series={detail.indices[activeIndex]} />
        ) : null}
      </Section>

      <Section title="Irrigation">
        <Row label="Last">
          {detail.irrigation.last
            ? `${daysAgo(detail.irrigation.last.date)} · ${detail.irrigation.last.volume_mm} mm`
            : "—"}
        </Row>
        <Row label="Next">
          {detail.irrigation.next ? (
            <span className={detail.irrigation.next.is_emergency ? "font-bold text-red-700" : ""}>
              {detail.irrigation.next.date} · {detail.irrigation.next.volume_mm} mm
            </span>
          ) : (
            "—"
          )}
        </Row>
        <Row label="Soil moisture">
          {detail.irrigation.soil_moisture_pct != null
            ? `${detail.irrigation.soil_moisture_pct}% (${detail.irrigation.soil_status})`
            : "—"}
        </Row>
      </Section>

      {detail.recommendations.length > 0 ? (
        <Section title="Recommendations">
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-[11px] leading-snug text-slate-700">
            {detail.recommendations.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </Section>
      ) : null}

      {activitiesNext.length + activitiesLater.length > 0 ? (
        <Section title="Planned activities">
          {activitiesNext.length > 0 ? (
            <>
              <h4 className="mt-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Next 7 days
              </h4>
              <ul className="mt-1 divide-y divide-slate-100 text-[11px]">
                {activitiesNext.map((a, i) => (
                  <li key={`n${i}`} className="flex gap-2 py-1">
                    <span className="w-16 shrink-0 text-slate-500">{a.date}</span>
                    <span className="text-slate-800">{a.label}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
          {activitiesLater.length > 0 ? (
            <>
              <h4 className="mt-2 text-[10px] font-medium uppercase tracking-wide text-slate-500">
                Later
              </h4>
              <ul className="mt-1 divide-y divide-slate-100 text-[11px]">
                {activitiesLater.map((a, i) => (
                  <li key={`l${i}`} className="flex gap-2 py-1">
                    <span className="w-16 shrink-0 text-slate-500">{a.date}</span>
                    <span className="text-slate-800">{a.label}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </Section>
      ) : null}

      {detail.signals.length > 0 ? (
        <Section title="Custom signals" hint="latest 30d">
          <ul className="mt-1 divide-y divide-slate-100 text-[11px]">
            {detail.signals.map((s, i) => (
              <li key={i} className="flex gap-2 py-1">
                <span className="w-24 shrink-0 truncate font-medium text-slate-700">{s.code}</span>
                <span className="flex-1 truncate text-slate-800">{s.value}</span>
                <span className="text-[10px] text-slate-500">{daysAgo(s.recorded_at)}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {detail.integration ? (
        <Section title="Integrations">
          <IntegrationRow label="Weather" status={detail.integration.weather} />
          <IntegrationRow label="Imagery" status={detail.integration.imagery} />
        </Section>
      ) : null}

      {detail.weather_3d.length > 0 ? (
        <Section title="Weather (3-day)">
          <div className="mt-1 grid grid-cols-3 gap-2">
            {detail.weather_3d.map((d, i) => (
              <div key={i} className="rounded-md border border-slate-200 bg-white p-2 text-center">
                <div className="text-[10px] text-slate-500">{d.day}</div>
                <div className="text-[13px] font-medium text-slate-900">
                  {d.temp_c_max != null ? `${Math.round(d.temp_c_max)}°` : "—"}
                </div>
              </div>
            ))}
          </div>
        </Section>
      ) : null}

      <button
        type="button"
        className="mt-4 w-full rounded-md bg-slate-900 py-2 text-xs font-medium text-white hover:bg-slate-800"
        onClick={() => alert("Stub: AI assistant integration not wired in v1.")}
      >
        Ask Claude what to do ↗
      </button>

      {onInactivate ? (
        <button
          type="button"
          onClick={onInactivate}
          className="mt-2 w-full rounded-md border border-red-300 py-2 text-xs font-medium text-red-700 hover:bg-red-50"
        >
          Inactivate block…
        </button>
      ) : null}
    </aside>
  );
}

function EditForm({
  block,
  saving,
  saveError,
  onCancel,
  onSubmit,
}: {
  block: Block;
  saving: boolean;
  saveError: string | null;
  onCancel: () => void;
  onSubmit: (patch: BlockUpdatePayload) => void;
}) {
  const [name, setName] = useState(block.name ?? "");
  const [irrigationSystem, setIrrigationSystem] = useState<IrrigationSystem | "">(
    block.irrigation_system ?? "",
  );
  const [irrigationSource, setIrrigationSource] = useState<IrrigationSource | "">(
    block.irrigation_source ?? "",
  );
  const [soilTexture, setSoilTexture] = useState<SoilTexture | "">(block.soil_texture ?? "");
  const [salinityClass, setSalinityClass] = useState<SalinityClass | "">(
    block.salinity_class ?? "",
  );
  const [soilPh, setSoilPh] = useState<string>(block.soil_ph != null ? String(block.soil_ph) : "");
  const [notes, setNotes] = useState(block.notes ?? "");
  const [tagsRaw, setTagsRaw] = useState((block.tags ?? []).join(", "));

  // Reseed if the underlying block changes (e.g. user closes + reopens edit).
  useEffect(() => {
    setName(block.name ?? "");
    setIrrigationSystem(block.irrigation_system ?? "");
    setIrrigationSource(block.irrigation_source ?? "");
    setSoilTexture(block.soil_texture ?? "");
    setSalinityClass(block.salinity_class ?? "");
    setSoilPh(block.soil_ph != null ? String(block.soil_ph) : "");
    setNotes(block.notes ?? "");
    setTagsRaw((block.tags ?? []).join(", "));
  }, [block.id]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const patch: BlockUpdatePayload = {
      name: name || null,
      irrigation_system: irrigationSystem === "" ? null : irrigationSystem,
      irrigation_source: irrigationSource === "" ? null : irrigationSource,
      soil_texture: soilTexture === "" ? null : soilTexture,
      salinity_class: salinityClass === "" ? null : salinityClass,
      soil_ph: soilPh === "" ? null : Number(soilPh),
      notes: notes || null,
      tags: tagsRaw
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    };
    onSubmit(patch);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mt-3 space-y-2 rounded border border-slate-200 bg-slate-50 p-2"
    >
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        Edit block
      </div>
      <label className="block text-[11px] text-slate-700">
        Name
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-[12px]"
        />
      </label>
      <label className="block text-[11px] text-slate-700">
        Irrigation system
        <select
          value={irrigationSystem}
          onChange={(e) => setIrrigationSystem(e.target.value as IrrigationSystem | "")}
          className="mt-0.5 block w-full rounded border border-slate-300 bg-white px-2 py-1 text-[12px]"
        >
          <option value="">—</option>
          {(
            [
              "drip",
              "micro_sprinkler",
              "pivot",
              "furrow",
              "flood",
              "surface",
              "none",
            ] as IrrigationSystem[]
          ).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-[11px] text-slate-700">
        Irrigation source
        <select
          value={irrigationSource}
          onChange={(e) => setIrrigationSource(e.target.value as IrrigationSource | "")}
          className="mt-0.5 block w-full rounded border border-slate-300 bg-white px-2 py-1 text-[12px]"
        >
          <option value="">—</option>
          {(["well", "canal", "nile", "mixed"] as IrrigationSource[]).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-[11px] text-slate-700">
        Soil texture
        <select
          value={soilTexture}
          onChange={(e) => setSoilTexture(e.target.value as SoilTexture | "")}
          className="mt-0.5 block w-full rounded border border-slate-300 bg-white px-2 py-1 text-[12px]"
        >
          <option value="">—</option>
          {(
            [
              "sandy",
              "sandy_loam",
              "loam",
              "clay_loam",
              "clay",
              "silty_loam",
              "silty_clay",
            ] as SoilTexture[]
          ).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-[11px] text-slate-700">
        Salinity class
        <select
          value={salinityClass}
          onChange={(e) => setSalinityClass(e.target.value as SalinityClass | "")}
          className="mt-0.5 block w-full rounded border border-slate-300 bg-white px-2 py-1 text-[12px]"
        >
          <option value="">—</option>
          {(
            [
              "non_saline",
              "slightly_saline",
              "moderately_saline",
              "strongly_saline",
            ] as SalinityClass[]
          ).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-[11px] text-slate-700">
        Soil pH
        <input
          type="number"
          min={0}
          max={14}
          step={0.1}
          value={soilPh}
          onChange={(e) => setSoilPh(e.target.value)}
          className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-[12px]"
        />
      </label>
      <label className="block text-[11px] text-slate-700">
        Tags (comma-separated)
        <input
          type="text"
          value={tagsRaw}
          onChange={(e) => setTagsRaw(e.target.value)}
          className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-[12px]"
        />
      </label>
      <label className="block text-[11px] text-slate-700">
        Notes
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          className="mt-0.5 block w-full rounded border border-slate-300 px-2 py-1 text-[12px]"
        />
      </label>
      {saveError ? (
        <p className="rounded bg-red-50 px-2 py-1 text-[11px] text-red-700">{saveError}</p>
      ) : null}
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={saving}
          className="rounded border border-slate-300 px-2 py-1 text-[11px] text-slate-700"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-slate-900 px-2 py-1 text-[11px] font-medium text-white disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
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

function IntegrationRow({ label, status }: { label: string; status: IntegrationKindStatus }) {
  const lastSync = status.last_sync_at ? formatRelative(status.last_sync_at) : "—";
  const lastFail = status.last_failed_at ? formatRelative(status.last_failed_at) : null;
  const tone =
    status.failed_24h > 0 || status.overdue_count > 0
      ? "text-amber-700"
      : status.active_subs > 0
        ? "text-emerald-700"
        : "text-slate-500";
  return (
    <div className="mt-1 rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-[11px]">
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-800">{label}</span>
        <span className={`text-[10px] ${tone}`}>
          {status.active_subs} sub{status.active_subs === 1 ? "" : "s"}
          {status.running_count > 0 ? ` · ${status.running_count} running` : ""}
          {status.overdue_count > 0 ? ` · ${status.overdue_count} overdue` : ""}
        </span>
      </div>
      <div className="mt-0.5 text-[10px] text-slate-500">
        Last sync {lastSync}
        {lastFail ? ` · last fail ${lastFail}` : ""}
        {status.failed_24h > 0 ? ` · ${status.failed_24h} failed (24h)` : ""}
      </div>
    </div>
  );
}

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {title}
        {hint ? <span className="ms-1 font-normal normal-case text-slate-400">{hint}</span> : null}
      </h3>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-1 flex justify-between gap-2 text-[11px]">
      <span className="text-slate-500">{label}:</span>
      <span className="text-right text-slate-800">{children}</span>
    </div>
  );
}

function Trend({ delta }: { delta: number | null }) {
  if (delta == null) {
    return <span className="text-[10px] text-slate-400">—</span>;
  }
  if (Math.abs(delta) <= 0.005) {
    return <span className="text-[10px] text-slate-500">~ {delta.toFixed(2)}</span>;
  }
  if (delta > 0) {
    return <span className="text-[10px] text-emerald-700">↑ +{delta.toFixed(2)}</span>;
  }
  return <span className="text-[10px] text-red-700">↓ {delta.toFixed(2)}</span>;
}

function formatRelative(iso: string): string {
  const t = new Date(iso).getTime();
  const diff = Date.now() - t;
  const hours = Math.round(diff / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function daysAgo(iso: string): string {
  const t = new Date(iso).getTime();
  const days = Math.round((Date.now() - t) / 86_400_000);
  if (days <= 0) return "today";
  return `${days}d ago`;
}
