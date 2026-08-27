import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { Polygon } from "geojson";

import { ensureValidPolygon, GeometryValidationError } from "@/lib/geometry";
import {
  type BlockCreatePayload,
  type IrrigationSource,
  type IrrigationSystem,
  type SalinityClass,
  type SoilTexture,
} from "@/api/blocks";
import { listTenantUsers, type TenantUser } from "@/api/users";
import { useCapability } from "@/rbac/useCapability";
import { MapDraw } from "./MapDraw";
import { AoiUploader } from "./AoiUploader";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { displayUser } from "@/lib/userDisplay";

const IRRIGATION_SYSTEMS: IrrigationSystem[] = [
  "drip",
  "micro_sprinkler",
  "pivot",
  "furrow",
  "flood",
  "surface",
  "none",
];
const IRRIGATION_SOURCES: IrrigationSource[] = ["well", "canal", "nile", "mixed"];
const SOIL_TEXTURES: SoilTexture[] = [
  "sandy",
  "sandy_loam",
  "loam",
  "clay_loam",
  "clay",
  "silty_loam",
  "silty_clay",
];
const SALINITY_CLASSES: SalinityClass[] = [
  "non_saline",
  "slightly_saline",
  "moderately_saline",
  "strongly_saline",
];

const CODE_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/;

export type BlockFormValues = BlockCreatePayload;

interface Props {
  initial?: Partial<BlockFormValues>;
  initialBoundary?: Polygon | null;
  submitLabel: string;
  onSubmit: (values: BlockFormValues) => Promise<void>;
  onCancel?: () => void;
  busy?: boolean;
  error?: string | null;
}

export function BlockForm({
  initial,
  initialBoundary,
  submitLabel,
  onSubmit,
  onCancel,
  busy,
  error,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("farms");
  const [code, setCode] = useState(initial?.code ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [nameAr, setNameAr] = useState(initial?.name_ar ?? "");
  const [irrigationSystem, setIrrigationSystem] = useState<IrrigationSystem | "">(
    initial?.irrigation_system ?? "",
  );
  const [irrigationSource, setIrrigationSource] = useState<IrrigationSource | "">(
    initial?.irrigation_source ?? "",
  );
  const [soilTexture, setSoilTexture] = useState<SoilTexture | "">(initial?.soil_texture ?? "");
  const [salinityClass, setSalinityClass] = useState<SalinityClass | "">(
    initial?.salinity_class ?? "",
  );
  const [soilPh, setSoilPh] = useState<string>(
    initial?.soil_ph != null ? String(initial.soil_ph) : "",
  );
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [drawnPolygon, setDrawnPolygon] = useState<Polygon | null>(initialBoundary ?? null);
  const [uploadedPolygon, setUploadedPolygon] = useState<Polygon | null>(null);
  const [boundaryError, setBoundaryError] = useState<string | null>(null);

  // U-4b: per-block agronomist picker. The agronomist is now a tenant
  // member (agronomist_membership_id). Only offered when the caller can
  // list members (user.read); otherwise the existing value is preserved
  // untouched. Members are optional context, so a load failure is silent.
  const canReadMembers = useCapability("user.read");
  const [members, setMembers] = useState<TenantUser[]>([]);
  const [agronomistMembershipId, setAgronomistMembershipId] = useState<string | null>(
    initial?.agronomist_membership_id ?? null,
  );
  useEffect(() => {
    if (!canReadMembers) return;
    let cancelled = false;
    listTenantUsers().then(
      (rows) => {
        if (!cancelled) setMembers(rows);
      },
      () => {
        /* members are optional context — ignore a load failure */
      },
    );
    return () => {
      cancelled = true;
    };
  }, [canReadMembers]);

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setBoundaryError(null);

    if (!CODE_RE.test(code)) {
      setBoundaryError(t("form.errors.codePattern"));
      return;
    }
    const sourceGeometry = uploadedPolygon ?? drawnPolygon;
    if (!sourceGeometry) {
      setBoundaryError(t("form.errors.boundaryRequired"));
      return;
    }
    let polygon: Polygon;
    try {
      polygon = ensureValidPolygon(sourceGeometry);
    } catch (err) {
      const code = (err as GeometryValidationError).code;
      if (code === "self_intersect") setBoundaryError(t("form.errors.boundarySelfIntersect"));
      else setBoundaryError(t("form.errors.boundaryInvalid"));
      return;
    }
    const payload: BlockFormValues = {
      code,
      name: name || null,
      // Blank means "not written yet"; the Arabic screens fall back to `name`.
      name_ar: nameAr.trim() || null,
      boundary: polygon,
      irrigation_system: irrigationSystem || null,
      irrigation_source: irrigationSource || null,
      soil_texture: soilTexture || null,
      salinity_class: salinityClass || null,
      soil_ph: soilPh ? Number(soilPh) : null,
      agronomist_membership_id: agronomistMembershipId,
      notes: notes || null,
      tags: [],
    };
    await onSubmit(payload);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6" aria-label={submitLabel}>
      <Card className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="block-code">
            {t("form.blockCode")}
          </label>
          <input
            id="block-code"
            className="input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            disabled={!!initial?.code}
          />
        </div>
        <div>
          <label className="label" htmlFor="block-name">
            {t("form.blockName")}
          </label>
          <input
            id="block-name"
            className="input"
            value={name ?? ""}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="block-name-ar">
            {t("form.blockNameAr")}
          </label>
          <input
            id="block-name-ar"
            className="input"
            // Always RTL: the field holds Arabic whatever the page language is.
            dir="rtl"
            lang="ar"
            value={nameAr ?? ""}
            onChange={(e) => setNameAr(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="block-irrigation-system">
            {t("form.irrigationSystem")}
          </label>
          <select
            id="block-irrigation-system"
            className="input"
            value={irrigationSystem}
            onChange={(e) => setIrrigationSystem(e.target.value as IrrigationSystem)}
          >
            <option value="">—</option>
            {IRRIGATION_SYSTEMS.map((v) => (
              <option key={v} value={v}>
                {t(`irrigationSystem.${v}`)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="block-irrigation-source">
            {t("form.irrigationSource")}
          </label>
          <select
            id="block-irrigation-source"
            className="input"
            value={irrigationSource}
            onChange={(e) => setIrrigationSource(e.target.value as IrrigationSource)}
          >
            <option value="">—</option>
            {IRRIGATION_SOURCES.map((v) => (
              <option key={v} value={v}>
                {t(`waterSource.${v}`)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="block-soil">
            {t("form.soilTexture")}
          </label>
          <select
            id="block-soil"
            className="input"
            value={soilTexture}
            onChange={(e) => setSoilTexture(e.target.value as SoilTexture)}
          >
            <option value="">—</option>
            {SOIL_TEXTURES.map((v) => (
              <option key={v} value={v}>
                {t(`soilTexture.${v}`)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="block-salinity">
            {t("form.salinityClass")}
          </label>
          <select
            id="block-salinity"
            className="input"
            value={salinityClass}
            onChange={(e) => setSalinityClass(e.target.value as SalinityClass)}
          >
            <option value="">—</option>
            {SALINITY_CLASSES.map((v) => (
              <option key={v} value={v}>
                {t(`salinity.${v}`)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="block-ph">
            {t("form.soilPh")}
          </label>
          <input
            id="block-ph"
            className="input"
            type="number"
            min={0}
            max={14}
            step={0.1}
            value={soilPh}
            onChange={(e) => setSoilPh(e.target.value)}
          />
        </div>
        {canReadMembers ? (
          <div>
            <label className="label" htmlFor="block-agronomist">
              {t("form.agronomist")}
            </label>
            <select
              id="block-agronomist"
              className="input"
              value={agronomistMembershipId ?? ""}
              onChange={(e) => setAgronomistMembershipId(e.target.value || null)}
            >
              <option value="">{t("form.agronomistNone")}</option>
              {members.map((m) => (
                <option key={m.membership_id} value={m.membership_id}>
                  {displayUser(m, m.membership_id, i18n.language)}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="sm:col-span-2">
          <label className="label" htmlFor="block-notes">
            {t("form.notes")}
          </label>
          <textarea
            id="block-notes"
            className="input"
            rows={2}
            value={notes ?? ""}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>
      </Card>

      <Card>
        <h2 className="text-lg font-semibold text-ap-ink">{t("form.blockBoundary")}</h2>
        <div className="mt-4">
          <MapDraw initial={drawnPolygon ?? null} onChange={setDrawnPolygon} />
        </div>
        <div className="mt-4">
          <AoiUploader
            onFeaturesParsed={(features) => {
              const f = features[0];
              setUploadedPolygon(f && f.geometry.type === "Polygon" ? f.geometry : null);
            }}
          />
        </div>
      </Card>

      {boundaryError ? (
        <p role="alert" className="text-sm text-ap-crit">
          {boundaryError}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-ap-crit">
          {error}
        </p>
      ) : null}

      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? t("actions.saving") : submitLabel}
        </Button>
        {onCancel ? (
          <Button variant="ghost" onClick={onCancel}>
            {t("form.cancel")}
          </Button>
        ) : null}
      </div>
    </form>
  );
}
