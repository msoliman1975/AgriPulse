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
import type { Country } from "@/api/countries";
import type { FarmType, OwnershipType, WaterSource } from "@/api/farms";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { CODE_RE } from "@/lib/codes";
import { m2ToUnit, unitToM2 } from "@/lib/units";
import type { AreaUnit } from "@/prefs/PrefsContext";
import { fieldLabel, ghostBtn, inputCls, primaryBtn } from "./ui";

function FloatingCard({ children, className }: { children: ReactNode; className?: string }): ReactNode {
  return (
    <div
      className={
        "absolute left-1/2 top-4 z-30 w-[340px] max-w-[92vw] -translate-x-1/2 rounded-2xl border border-ap-line bg-ap-panel p-4 shadow-card " +
        (className ?? "")
      }
    >
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
  kind: "block" | "pivot" | "farm";
  vertices?: number;
  areaM2?: number;
  onCancel: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  return (
    <div className="absolute left-1/2 top-4 z-20 flex -translate-x-1/2 items-center gap-3 rounded-full bg-ap-ink/85 px-4 py-2 text-xs text-white shadow-card">
      <span className="font-semibold">
        {kind === "pivot" ? t("create.pivotDrawing") : kind === "farm" ? t("create.farmDrawing") : t("create.blockDrawing")}
      </span>
      {kind !== "pivot" && vertices != null && vertices > 0 ? (
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

// ---- Create farm: step 1, capture the boundary -----------------------------
// A farm cannot exist without a boundary (the backend requires it), so the
// flow leads with the map: draw the outline, or upload a KML / GeoJSON /
// zipped Shapefile. Parsing happens at the page level; this bar only emits
// the picked File.

export function FarmBoundaryBar({
  drawing,
  vertices,
  areaM2,
  parsing,
  error,
  onStartDraw,
  onFile,
  onCancel,
}: {
  drawing: boolean;
  vertices?: number;
  areaM2?: number;
  parsing: boolean;
  error: string | null;
  onStartDraw: () => void;
  onFile: (file: File) => void;
  onCancel: () => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  return (
    <FloatingCard className="!w-[380px]">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-bold text-ap-ink">{t("create.farmTitle")}</h3>
          <p className="mt-0.5 text-xs text-ap-muted">{t("create.boundaryHint")}</p>
        </div>
        <button type="button" onClick={onCancel} className="grid h-7 w-7 flex-none place-items-center rounded-lg text-ap-muted hover:bg-ap-line/50" aria-label={t("manage.cancel")}>
          ✕
        </button>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button type="button" onClick={onStartDraw} disabled={parsing} className={(drawing ? primaryBtn : ghostBtn) + " flex-1"}>
          ✏ {t("create.drawBoundary")}
        </button>
        <label className={ghostBtn + " flex-1 cursor-pointer text-center leading-9"}>
          ⬆ {parsing ? t("create.parsing") : t("create.uploadBoundary")}
          <input
            type="file"
            accept=".geojson,.json,.zip,.kml,application/geo+json,application/json,application/zip,application/vnd.google-earth.kml+xml"
            className="sr-only"
            disabled={parsing}
            onChange={(e) => {
              const f = e.target.files?.[0];
              // Reset the input so re-picking the same file fires onChange again.
              e.target.value = "";
              if (f) onFile(f);
            }}
          />
        </label>
      </div>

      {drawing ? (
        <p className="mt-2 text-xs text-ap-muted">
          {t("create.farmDrawing")}
          {vertices != null && vertices > 0 ? (
            <>
              {" · "}
              {t("create.points", { n: vertices })}
              {areaM2 && areaM2 > 0 ? (
                <>
                  {" · "}
                  <AreaDisplay areaM2={areaM2} />
                </>
              ) : null}
            </>
          ) : null}
        </p>
      ) : null}
      {error ? <div className="mt-2 rounded-lg bg-ap-crit/10 px-3 py-1.5 text-xs text-ap-crit">{error}</div> : null}
    </FloatingCard>
  );
}

// ---- Create farm: step 2, name it ------------------------------------------
// Asks for the three fields that matter at creation time; everything else is
// behind "More details" because it is all editable afterwards in
// ⚙ Farm settings → Farm. Field labels reuse the `farms` namespace so the
// wording stays identical to the (legacy) farm edit form.

export interface FarmDraft {
  code: string;
  name: string;
  country_code: string | null;
  description: string | null;
  governorate: string | null;
  district: string | null;
  nearest_city: string | null;
  address_line: string | null;
  farm_type: FarmType;
  ownership_type: OwnershipType | null;
  primary_water_source: WaterSource | null;
  established_date: string | null;
  tags: string[];
}

const FARM_TYPES: FarmType[] = ["commercial", "research", "contract"];
const OWNERSHIP_TYPES: OwnershipType[] = ["owned", "leased", "partnership", "other"];
const WATER_SOURCES: WaterSource[] = ["well", "canal", "nile", "desalinated", "rainfed", "mixed"];

export function CreateFarmPanel({
  areaM2,
  countries,
  submitting,
  error,
  onSubmit,
  onBack,
  onCancel,
}: {
  areaM2: number;
  countries: Country[];
  submitting: boolean;
  error: string | null;
  onSubmit: (draft: FarmDraft) => void;
  onBack: () => void;
  onCancel: () => void;
}): ReactNode {
  const { t, i18n } = useTranslation("farmConsole");
  const { t: tf } = useTranslation("farms");
  const isAr = i18n.language === "ar";
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [country, setCountry] = useState("");
  const [more, setMore] = useState(false);
  const [description, setDescription] = useState("");
  const [governorate, setGovernorate] = useState("");
  const [district, setDistrict] = useState("");
  const [nearestCity, setNearestCity] = useState("");
  const [addressLine, setAddressLine] = useState("");
  const [farmType, setFarmType] = useState<FarmType>("commercial");
  const [ownership, setOwnership] = useState<OwnershipType | "">("");
  const [water, setWater] = useState<WaterSource | "">("");
  const [established, setEstablished] = useState("");
  const [tags, setTags] = useState("");

  // Same contract as the legacy farm form: code must match the API pattern,
  // name is required. Everything else is optional at creation time.
  const codeError = code.trim().length === 0 ? t("create.codeRequired") : !CODE_RE.test(code.trim()) ? tf("form.errors.codePattern") : null;
  const nameError = name.trim().length === 0 ? tf("form.errors.nameRequired") : null;
  const invalid = codeError != null || nameError != null;

  return (
    <FloatingCard className="!w-[400px] max-h-[calc(100%-2rem)] overflow-auto">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-bold text-ap-ink">{t("create.farmTitle")}</h3>
          <p className="mt-0.5 text-xs text-ap-muted">
            <AreaDisplay areaM2={areaM2} /> · {t("create.farmEditLater")}
          </p>
        </div>
        <button type="button" onClick={onCancel} className="grid h-7 w-7 flex-none place-items-center rounded-lg text-ap-muted hover:bg-ap-line/50" aria-label={t("manage.cancel")}>
          ✕
        </button>
      </div>

      <form
        className="mt-3 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (invalid) return;
          onSubmit({
            code: code.trim(),
            name: name.trim(),
            country_code: country || null,
            description: description.trim() || null,
            governorate: governorate.trim() || null,
            district: district.trim() || null,
            nearest_city: nearestCity.trim() || null,
            address_line: addressLine.trim() || null,
            farm_type: farmType,
            ownership_type: ownership || null,
            primary_water_source: water || null,
            established_date: established || null,
            tags: tags.split(",").map((s) => s.trim()).filter(Boolean),
          });
        }}
      >
        {/* Help and error text sit OUTSIDE the label so they don't end up in
            the field's accessible name. */}
        <div>
          <label className="block">
            <span className={fieldLabel}>{tf("form.code")}</span>
            <input className={inputCls} value={code} onChange={(e) => setCode(e.target.value)} placeholder={t("create.farmCodePlaceholder")} disabled={submitting} />
          </label>
          {code.trim().length > 0 && codeError ? <p className="mt-1 text-xs text-ap-crit">{codeError}</p> : null}
        </div>
        <label className="block">
          <span className={fieldLabel}>{tf("form.name")}</span>
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder={t("create.farmNamePlaceholder")} disabled={submitting} />
        </label>
        <label className="block">
          <span className={fieldLabel}>{tf("form.country")}</span>
          <select className={inputCls} value={country} onChange={(e) => setCountry(e.target.value)} disabled={submitting}>
            <option value="">{tf("form.countryNone")}</option>
            {countries.map((c) => (
              <option key={c.code} value={c.code}>
                {isAr ? c.name_ar : c.name_en}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={() => setMore((m) => !m)}
          className="flex w-full items-center gap-1.5 rounded-lg px-1 py-1 text-start text-xs font-semibold text-ap-primary hover:bg-ap-primary-soft"
        >
          <span className={"transition-transform " + (more ? "rotate-90" : "")}>›</span>
          {t("create.moreDetails")}
        </button>

        {more ? (
          <div className="space-y-3 rounded-xl border border-ap-line p-3">
            <label className="block">
              <span className={fieldLabel}>{tf("form.description")}</span>
              <textarea className={inputCls} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} disabled={submitting} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className={fieldLabel}>{tf("form.governorate")}</span>
                <input className={inputCls} value={governorate} onChange={(e) => setGovernorate(e.target.value)} disabled={submitting} />
              </label>
              <label className="block">
                <span className={fieldLabel}>{tf("form.district")}</span>
                <input className={inputCls} value={district} onChange={(e) => setDistrict(e.target.value)} disabled={submitting} />
              </label>
              <label className="block">
                <span className={fieldLabel}>{tf("form.nearestCity")}</span>
                <input className={inputCls} value={nearestCity} onChange={(e) => setNearestCity(e.target.value)} disabled={submitting} />
              </label>
              <label className="block">
                <span className={fieldLabel}>{tf("form.addressLine")}</span>
                <input className={inputCls} value={addressLine} onChange={(e) => setAddressLine(e.target.value)} disabled={submitting} />
              </label>
              <label className="block">
                <span className={fieldLabel}>{tf("form.farmType")}</span>
                <select className={inputCls} value={farmType} onChange={(e) => setFarmType(e.target.value as FarmType)} disabled={submitting}>
                  {FARM_TYPES.map((v) => (
                    <option key={v} value={v}>
                      {tf(`farmType.${v}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className={fieldLabel}>{tf("form.ownershipType")}</span>
                <select className={inputCls} value={ownership} onChange={(e) => setOwnership(e.target.value as OwnershipType | "")} disabled={submitting}>
                  <option value="">—</option>
                  {OWNERSHIP_TYPES.map((v) => (
                    <option key={v} value={v}>
                      {tf(`ownershipType.${v}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className={fieldLabel}>{tf("form.primaryWaterSource")}</span>
                <select className={inputCls} value={water} onChange={(e) => setWater(e.target.value as WaterSource | "")} disabled={submitting}>
                  <option value="">—</option>
                  {WATER_SOURCES.map((v) => (
                    <option key={v} value={v}>
                      {tf(`waterSource.${v}`)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className={fieldLabel}>{tf("form.establishedDate")}</span>
                <input type="date" className={inputCls} value={established} onChange={(e) => setEstablished(e.target.value)} disabled={submitting} />
              </label>
            </div>
            <div>
              <label className="block">
                <span className={fieldLabel}>{tf("form.tags")}</span>
                <input className={inputCls} value={tags} onChange={(e) => setTags(e.target.value)} disabled={submitting} />
              </label>
              <p className="mt-1 text-xs text-ap-muted">{tf("form.tagsHelp")}</p>
            </div>
          </div>
        ) : null}

        {error ? <div className="rounded-lg bg-ap-crit/10 px-3 py-1.5 text-xs text-ap-crit">{error}</div> : null}

        <div className="flex items-center gap-2 pt-1">
          <button type="button" onClick={onBack} disabled={submitting} className={ghostBtn}>
            ↩ {t("create.redrawBoundary")}
          </button>
          <button type="submit" disabled={submitting || invalid} className={primaryBtn + " ms-auto"}>
            {submitting ? t("manage.saving") : t("create.createFarm")}
          </button>
        </div>
      </form>
    </FloatingCard>
  );
}

// ---- Auto-block (max area → compute → pick → create) -----------------------

export function AutoBlockPanel({
  maxAreaM2,
  onMaxAreaM2,
  unit,
  effectiveCellSizeM,
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
  // Canonical per-block area cap in m²; the input renders/accepts it in the
  // user's preferred area unit. effectiveCellSizeM is the grid cell the
  // backend actually applied (echoed from the last compute), or null.
  maxAreaM2: number;
  onMaxAreaM2: (m2: number) => void;
  unit: AreaUnit;
  effectiveCellSizeM: number | null;
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
  const { t: tArea } = useTranslation("farms");
  const selectedArea = (candidates ?? [])
    .filter((c) => selected.has(c.code))
    .reduce((sum, c) => sum + Number(c.area_m2), 0);
  const allSelected = candidates != null && candidates.length > 0 && selected.size === candidates.length;
  // Show the cap in the user's unit, rounded to 2 dp so the number input stays
  // tidy; round-trip through unitToM2 on edit keeps m² as the source of truth.
  const maxAreaInUnit = Math.round(m2ToUnit(maxAreaM2, unit) * 100) / 100;

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
          <span className="mb-1 block text-xs font-semibold text-ap-muted">
            {t("autoBlock.maxArea", { unit: tArea(`area.${unit}`) })}
          </span>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={0.1}
              step={0.5}
              className={inputCls}
              value={maxAreaInUnit}
              onChange={(e) => onMaxAreaM2(unitToM2(Number(e.target.value), unit))}
              disabled={computing || creating}
            />
            <button type="button" onClick={onCompute} disabled={computing || creating} className={primaryBtn + " flex-none"}>
              {computing ? t("autoBlock.computing") : t("autoBlock.compute")}
            </button>
          </div>
          {effectiveCellSizeM != null ? (
            <span className="mt-1 block text-xs text-ap-muted">
              {t("autoBlock.cellNote", { m: effectiveCellSizeM })}
            </span>
          ) : null}
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
