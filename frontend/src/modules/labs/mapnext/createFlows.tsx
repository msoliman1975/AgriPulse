// Native create flows for the Farm Console — themed (ap-* tokens) panels
// that float over the console map, replacing the old deep-linked screens
// (/blocks/new, /blocks/auto-grid, legacy map pivot). They reuse the
// MapCanvas draw primitives wired up in FarmConsolePage; this file is just
// the capture UI: code+name for a drawn block, code+name+sectors for a
// drawn pivot, and a cell-size → compute → pick → create panel for
// auto-blocking (with a live candidate preview painted on the map).
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AutoGridCandidate } from "@/api/blocks";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";

const inputCls =
  "w-full rounded-lg border border-ap-line bg-ap-panel px-3 py-2 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";
const primaryBtn =
  "h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white disabled:opacity-50 hover:bg-ap-primary/90";
const ghostBtn =
  "h-9 rounded-lg border border-ap-line bg-ap-panel px-3 text-sm font-semibold text-ap-ink hover:bg-ap-primary-soft disabled:opacity-50";

function FloatingCard({ children }: { children: ReactNode }): ReactNode {
  return (
    <div className="absolute left-1/2 top-4 z-30 w-[340px] max-w-[92vw] -translate-x-1/2 rounded-2xl border border-ap-line bg-ap-panel p-4 shadow-card">
      {children}
    </div>
  );
}

// ---- Draw-in-progress hint -------------------------------------------------

export function DrawHintBar({
  kind,
  vertices,
  areaM2,
  onCancel,
}: {
  kind: "block" | "pivot";
  vertices?: number;
  areaM2?: number;
  onCancel: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  return (
    <div className="absolute left-1/2 top-4 z-20 flex -translate-x-1/2 items-center gap-3 rounded-full bg-ap-ink/85 px-4 py-2 text-xs text-white shadow-card">
      <span className="font-semibold">{kind === "pivot" ? t("create.pivotDrawing") : t("create.blockDrawing")}</span>
      {kind === "block" && vertices != null && vertices > 0 ? (
        <span className="text-white/80">
          {t("create.points", { n: vertices })}
          {areaM2 && areaM2 > 0 ? (
            <>
              {" · "}
              <AreaDisplay areaM2={areaM2} />
            </>
          ) : null}
        </span>
      ) : null}
      <button type="button" onClick={onCancel} className="rounded-full bg-white/20 px-2.5 py-0.5 font-semibold hover:bg-white/30">
        {t("manage.cancel")}
      </button>
    </div>
  );
}

// ---- Create block (from a drawn polygon) -----------------------------------

export function CreateBlockPanel({
  areaM2,
  submitting,
  error,
  onSubmit,
  onCancel,
}: {
  areaM2: number;
  submitting: boolean;
  error: string | null;
  onSubmit: (v: { code: string; name: string }) => void;
  onCancel: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const codeError = code.trim().length === 0 ? t("create.codeRequired") : null;
  return (
    <FloatingCard>
      <h3 className="text-base font-bold text-ap-ink">{t("create.blockTitle")}</h3>
      <p className="mt-0.5 text-xs text-ap-muted">
        <AreaDisplay areaM2={areaM2} /> · {t("create.editLater")}
      </p>
      <form
        className="mt-3 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (codeError) return;
          onSubmit({ code: code.trim(), name: name.trim() });
        }}
      >
        <label className="block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("create.code")}</span>
          <input className={inputCls} value={code} onChange={(e) => setCode(e.target.value)} placeholder={t("create.codePlaceholder")} disabled={submitting} />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("create.nameOptional")}</span>
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder={t("create.blockNamePlaceholder")} disabled={submitting} />
        </label>
        {error ? <div className="rounded-lg bg-ap-crit/10 px-3 py-1.5 text-xs text-ap-crit">{error}</div> : null}
        <div className="flex items-center justify-end gap-2 pt-1">
          <button type="button" onClick={onCancel} disabled={submitting} className={ghostBtn}>
            {t("manage.cancel")}
          </button>
          <button type="submit" disabled={submitting || codeError != null} className={primaryBtn}>
            {submitting ? t("manage.saving") : t("create.createBlock")}
          </button>
        </div>
      </form>
    </FloatingCard>
  );
}

// ---- Create pivot (from a drawn center+radius) -----------------------------

const SECTOR_PRESETS = [1, 4, 6, 8, 12];

export function CreatePivotPanel({
  centerLat,
  centerLon,
  radiusM,
  submitting,
  error,
  onSubmit,
  onCancel,
}: {
  centerLat: number;
  centerLon: number;
  radiusM: number;
  submitting: boolean;
  error: string | null;
  onSubmit: (v: { code: string; name: string; sector_count: number }) => void;
  onCancel: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [sectorCount, setSectorCount] = useState(4);
  const areaM2 = Math.PI * radiusM * radiusM;
  const codeError = code.trim().length === 0 ? t("create.codeRequired") : null;
  return (
    <FloatingCard>
      <h3 className="text-base font-bold text-ap-ink">{t("create.pivotTitle")}</h3>
      <p className="mt-0.5 text-xs text-ap-muted">
        {centerLat.toFixed(5)}, {centerLon.toFixed(5)} · {t("create.radius", { m: Math.round(radiusM) })} · <AreaDisplay areaM2={areaM2} />
      </p>
      <form
        className="mt-3 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (codeError) return;
          onSubmit({ code: code.trim(), name: name.trim(), sector_count: sectorCount });
        }}
      >
        <label className="block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("create.code")}</span>
          <input className={inputCls} value={code} onChange={(e) => setCode(e.target.value)} placeholder={t("create.pivotCodePlaceholder")} disabled={submitting} />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("create.nameOptional")}</span>
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder={t("create.pivotNamePlaceholder")} disabled={submitting} />
        </label>
        <div>
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("create.sectors")}</span>
          <div className="flex flex-wrap items-center gap-1.5">
            {SECTOR_PRESETS.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setSectorCount(n)}
                disabled={submitting}
                className={
                  "h-8 w-9 rounded-lg text-sm font-semibold " +
                  (n === sectorCount ? "bg-ap-primary text-white" : "border border-ap-line text-ap-ink hover:bg-ap-primary-soft")
                }
              >
                {n}
              </button>
            ))}
            <input
              type="number"
              min={1}
              max={16}
              value={sectorCount}
              onChange={(e) => setSectorCount(Math.max(1, Math.min(16, Number(e.target.value) || 1)))}
              disabled={submitting}
              className="h-8 w-16 rounded-lg border border-ap-line bg-ap-panel px-2 text-sm text-ap-ink"
            />
          </div>
        </div>
        {error ? <div className="rounded-lg bg-ap-crit/10 px-3 py-1.5 text-xs text-ap-crit">{error}</div> : null}
        <div className="flex items-center justify-end gap-2 pt-1">
          <button type="button" onClick={onCancel} disabled={submitting} className={ghostBtn}>
            {t("manage.cancel")}
          </button>
          <button type="submit" disabled={submitting || codeError != null} className={primaryBtn}>
            {submitting ? t("manage.saving") : t("create.createPivot")}
          </button>
        </div>
      </form>
    </FloatingCard>
  );
}

// ---- Auto-block (cell size → compute → pick → create) ----------------------

export function AutoBlockPanel({
  cellSize,
  onCellSize,
  onCompute,
  computing,
  candidates,
  selected,
  onToggle,
  onToggleAll,
  creating,
  progressDone,
  error,
  onCreate,
  onClose,
}: {
  cellSize: number;
  onCellSize: (v: number) => void;
  onCompute: () => void;
  computing: boolean;
  candidates: AutoGridCandidate[] | null;
  selected: Set<string>;
  onToggle: (code: string) => void;
  onToggleAll: (all: boolean) => void;
  creating: boolean;
  progressDone: number | null;
  error: string | null;
  onCreate: () => void;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const selectedArea = (candidates ?? [])
    .filter((c) => selected.has(c.code))
    .reduce((sum, c) => sum + Number(c.area_m2), 0);
  const allSelected = candidates != null && candidates.length > 0 && selected.size === candidates.length;

  return (
    <div className="absolute start-3 top-3 z-30 flex max-h-[calc(100%-1.5rem)] w-[300px] max-w-[88vw] flex-col rounded-2xl border border-ap-line bg-ap-panel shadow-card">
      <div className="flex items-center gap-2 border-b border-ap-line px-4 py-3">
        <span className="text-base">▩</span>
        <h3 className="text-sm font-bold text-ap-ink">{t("autoBlock.title")}</h3>
        <button type="button" onClick={onClose} className="ms-auto grid h-7 w-7 place-items-center rounded-lg text-ap-muted hover:bg-ap-line/50" aria-label={t("manage.cancel")}>
          ✕
        </button>
      </div>

      <div className="border-b border-ap-line p-4">
        <label className="block">
          <span className="mb-1 block text-xs font-semibold text-ap-muted">{t("autoBlock.cellSize")}</span>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={10}
              max={5000}
              step={10}
              className={inputCls}
              value={cellSize}
              onChange={(e) => onCellSize(Number(e.target.value))}
              disabled={computing || creating}
            />
            <button type="button" onClick={onCompute} disabled={computing || creating} className={primaryBtn + " flex-none"}>
              {computing ? t("autoBlock.computing") : t("autoBlock.compute")}
            </button>
          </div>
        </label>
      </div>

      {candidates == null ? (
        <div className="p-4 text-xs text-ap-muted">{t("autoBlock.hint")}</div>
      ) : candidates.length === 0 ? (
        <div className="p-4 text-xs text-ap-muted">{t("autoBlock.empty")}</div>
      ) : (
        <>
          <div className="flex items-center justify-between px-4 py-2 text-xs">
            <label className="inline-flex items-center gap-1.5 font-semibold text-ap-ink">
              <input type="checkbox" checked={allSelected} onChange={(e) => onToggleAll(e.target.checked)} className="accent-ap-primary" />
              {t("autoBlock.count", { n: candidates.length })}
            </label>
            <span className="text-ap-muted">
              {selected.size} · <AreaDisplay areaM2={selectedArea} />
            </span>
          </div>
          <ul className="min-h-0 flex-1 divide-y divide-ap-line/60 overflow-auto px-2">
            {candidates.map((c) => (
              <li key={c.code}>
                <label className="flex items-center gap-2 px-2 py-1.5 text-sm">
                  <input type="checkbox" checked={selected.has(c.code)} onChange={() => onToggle(c.code)} className="accent-ap-primary" />
                  <span className="font-mono text-xs text-ap-ink">{c.code}</span>
                  <span className="ms-auto text-xs text-ap-muted">
                    <AreaDisplay areaM2={Number(c.area_m2)} />
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </>
      )}

      {error ? <div className="mx-4 mb-2 rounded-lg bg-ap-crit/10 px-3 py-1.5 text-xs text-ap-crit">{error}</div> : null}

      <div className="flex items-center gap-2 border-t border-ap-line p-3">
        <button
          type="button"
          onClick={onCreate}
          disabled={creating || computing || selected.size === 0}
          className={primaryBtn + " flex-1"}
        >
          {creating
            ? progressDone != null
              ? t("autoBlock.creatingProgress", { done: progressDone, total: selected.size })
              : t("manage.saving")
            : t("autoBlock.create", { n: selected.size })}
        </button>
      </div>
    </div>
  );
}
