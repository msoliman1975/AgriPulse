import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { MultiPolygon, Polygon } from "geojson";

import {
  ensureValidMultiPolygon,
  GeometryValidationError,
  polygonToMultiPolygon,
} from "@/lib/geometry";
import {
  type FarmCreatePayload,
  type FarmType,
  type OwnershipType,
  type WaterSource,
} from "@/api/farms";
import { singleBoundary } from "@/lib/aoi";
import { MapDraw } from "./MapDraw";
import { AoiUploader } from "./AoiUploader";

const FARM_TYPES: FarmType[] = ["commercial", "research", "contract"];
const OWNERSHIP_TYPES: OwnershipType[] = ["owned", "leased", "partnership", "other"];
const WATER_SOURCES: WaterSource[] = ["well", "canal", "nile", "desalinated", "rainfed", "mixed"];

const CODE_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/;

export type FarmFormValues = FarmCreatePayload;

interface Props {
  initial?: Partial<FarmFormValues>;
  submitLabel: string;
  onSubmit: (values: FarmFormValues) => Promise<void>;
  onCancel?: () => void;
  busy?: boolean;
  error?: string | null;
}

export function FarmForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
  busy,
  error,
}: Props): ReactNode {
  const { t } = useTranslation("farms");
  const [code, setCode] = useState(initial?.code ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [governorate, setGovernorate] = useState(initial?.governorate ?? "");
  const [district, setDistrict] = useState(initial?.district ?? "");
  const [nearestCity, setNearestCity] = useState(initial?.nearest_city ?? "");
  const [addressLine, setAddressLine] = useState(initial?.address_line ?? "");
  const [farmType, setFarmType] = useState<FarmType>(initial?.farm_type ?? "commercial");
  const [ownershipType, setOwnershipType] = useState<OwnershipType | "">(
    initial?.ownership_type ?? "",
  );
  const [waterSource, setWaterSource] = useState<WaterSource | "">(
    initial?.primary_water_source ?? "",
  );
  const [established, setEstablished] = useState(initial?.established_date ?? "");
  const [tags, setTags] = useState<string>((initial?.tags ?? []).join(", "));
  const [drawnPolygon, setDrawnPolygon] = useState<Polygon | null>(null);
  const [uploadedBoundary, setUploadedBoundary] = useState<MultiPolygon | Polygon | null>(null);
  const [boundaryError, setBoundaryError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setBoundaryError(null);

    if (!CODE_RE.test(code)) {
      setBoundaryError(t("form.errors.codePattern"));
      return;
    }
    if (!name.trim()) {
      setBoundaryError(t("form.errors.nameRequired"));
      return;
    }

    const sourceGeometry: Polygon | MultiPolygon | null = uploadedBoundary ?? drawnPolygon;
    if (!sourceGeometry) {
      setBoundaryError(t("form.errors.boundaryRequired"));
      return;
    }

    let boundary: MultiPolygon;
    try {
      boundary = ensureValidMultiPolygon(
        sourceGeometry.type === "Polygon" ? polygonToMultiPolygon(sourceGeometry) : sourceGeometry,
      );
    } catch (err) {
      const code = (err as GeometryValidationError).code;
      if (code === "self_intersect") setBoundaryError(t("form.errors.boundarySelfIntersect"));
      else if (code === "out_of_egypt") setBoundaryError(t("form.errors.boundaryOutOfEgypt"));
      else setBoundaryError(t("form.errors.boundaryInvalid"));
      return;
    }

    const payload: FarmFormValues = {
      code,
      name,
      description: description || null,
      boundary,
      governorate: governorate || null,
      district: district || null,
      nearest_city: nearestCity || null,
      address_line: addressLine || null,
      farm_type: farmType,
      ownership_type: ownershipType || null,
      primary_water_source: waterSource || null,
      established_date: established || null,
      tags: tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean),
    };

    await onSubmit(payload);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6" aria-label={submitLabel}>
      <div className="card grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className="label" htmlFor="farm-code">
            {t("form.code")}
          </label>
          <input
            id="farm-code"
            className="input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            disabled={!!initial?.code}
          />
          <p className="mt-1 text-xs text-slate-500">{t("form.codeHelp")}</p>
        </div>
        <div>
          <label className="label" htmlFor="farm-name">
            {t("form.name")}
          </label>
          <input
            id="farm-name"
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="farm-description">
            {t("form.description")}
          </label>
          <textarea
            id="farm-description"
            className="input"
            rows={2}
            value={description ?? ""}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="farm-gov">
            {t("form.governorate")}
          </label>
          <input
            id="farm-gov"
            className="input"
            value={governorate ?? ""}
            onChange={(e) => setGovernorate(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="farm-district">
            {t("form.district")}
          </label>
          <input
            id="farm-district"
            className="input"
            value={district ?? ""}
            onChange={(e) => setDistrict(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="farm-city">
            {t("form.nearestCity")}
          </label>
          <input
            id="farm-city"
            className="input"
            value={nearestCity ?? ""}
            onChange={(e) => setNearestCity(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="farm-address">
            {t("form.addressLine")}
          </label>
          <input
            id="farm-address"
            className="input"
            value={addressLine ?? ""}
            onChange={(e) => setAddressLine(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="farm-type">
            {t("form.farmType")}
          </label>
          <select
            id="farm-type"
            className="input"
            value={farmType}
            onChange={(e) => setFarmType(e.target.value as FarmType)}
          >
            {FARM_TYPES.map((v) => (
              <option key={v} value={v}>
                {t(`farmType.${v}`)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="farm-ownership">
            {t("form.ownershipType")}
          </label>
          <select
            id="farm-ownership"
            className="input"
            value={ownershipType}
            onChange={(e) => setOwnershipType(e.target.value as OwnershipType)}
          >
            <option value="">—</option>
            {OWNERSHIP_TYPES.map((v) => (
              <option key={v} value={v}>
                {t(`ownershipType.${v}`)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="farm-water">
            {t("form.primaryWaterSource")}
          </label>
          <select
            id="farm-water"
            className="input"
            value={waterSource}
            onChange={(e) => setWaterSource(e.target.value as WaterSource)}
          >
            <option value="">—</option>
            {WATER_SOURCES.map((v) => (
              <option key={v} value={v}>
                {t(`waterSource.${v}`)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="farm-established">
            {t("form.establishedDate")}
          </label>
          <input
            id="farm-established"
            className="input"
            type="date"
            value={established ?? ""}
            onChange={(e) => setEstablished(e.target.value)}
          />
        </div>
        <div className="sm:col-span-2">
          <label className="label" htmlFor="farm-tags">
            {t("form.tags")}
          </label>
          <input
            id="farm-tags"
            className="input"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
          />
          <p className="mt-1 text-xs text-slate-500">{t("form.tagsHelp")}</p>
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-slate-800">{t("form.boundary")}</h2>
        <p className="mt-1 text-sm text-slate-600">{t("form.boundaryHelp")}</p>
        <div className="mt-4">
          <MapDraw onChange={setDrawnPolygon} />
        </div>
        <div className="mt-4">
          <AoiUploader
            onFeaturesParsed={(features) => setUploadedBoundary(singleBoundary(features))}
          />
        </div>
      </div>

      {boundaryError ? (
        <p role="alert" className="text-sm text-red-700">
          {boundaryError}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}

      <div className="flex gap-2">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? t("actions.saving") : submitLabel}
        </button>
        {onCancel ? (
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            {t("form.cancel")}
          </button>
        ) : null}
      </div>
    </form>
  );
}
