import { useEffect, useState, type FormEvent, type ReactNode } from "react";
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
import { listCountries, type Country } from "@/api/countries";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Field, FIELD_CONTROL_CLASS } from "@/components/Field";
import { FormFooter } from "@/components/FormFooter";
import { CODE_RE } from "@/lib/codes";
import { singleBoundary } from "@/lib/aoi";
import { MapDraw } from "./MapDraw";
import { AoiUploader } from "./AoiUploader";

const FARM_TYPES: FarmType[] = ["commercial", "research", "contract"];
const OWNERSHIP_TYPES: OwnershipType[] = ["owned", "leased", "partnership", "other"];
const WATER_SOURCES: WaterSource[] = ["well", "canal", "nile", "desalinated", "rainfed", "mixed"];

export type FarmFormValues = FarmCreatePayload;

interface Props {
  initial?: Partial<FarmFormValues>;
  submitLabel: string;
  onSubmit: (values: FarmFormValues) => Promise<void>;
  onCancel?: () => void;
  busy?: boolean;
  error?: string | null;
}

/**
 * The reference FormPage body: <Card title/footer> + <Field> + <FormFooter>.
 *
 * Shared by farm create and edit, so converting it once covers both. Field
 * ids, `aria-describedby` and `aria-invalid` are wired by <Field> rather than
 * hand-numbered, and help text sits outside the <label> so it doesn't end up
 * in the control's accessible name.
 */
export function FarmForm({
  initial,
  submitLabel,
  onSubmit,
  onCancel,
  busy,
  error,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("farms");
  const isAr = i18n.language === "ar";
  const [code, setCode] = useState(initial?.code ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [nameAr, setNameAr] = useState(initial?.name_ar ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [descriptionAr, setDescriptionAr] = useState(initial?.description_ar ?? "");
  const [country, setCountry] = useState(initial?.country_code ?? "");
  const [countries, setCountries] = useState<Country[]>([]);
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

  useEffect(() => {
    let active = true;
    listCountries()
      .then((rows) => {
        if (active) setCountries(rows);
      })
      .catch(() => {
        // Catalog read is best-effort; the field just stays empty on failure.
      });
    return () => {
      active = false;
    };
  }, []);

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
      else setBoundaryError(t("form.errors.boundaryInvalid"));
      return;
    }

    const payload: FarmFormValues = {
      code,
      name,
      // Blank means "not written yet", not an empty name. The API stores
      // NULL and every Arabic screen falls back to `name`.
      name_ar: nameAr.trim() || null,
      description: description || null,
      description_ar: descriptionAr.trim() || null,
      boundary,
      country_code: country || null,
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
        .map((tag) => tag.trim())
        .filter(Boolean),
    };

    await onSubmit(payload);
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label={submitLabel}>
      <Card
        title={t("form.identity")}
        bodyClassName="grid grid-cols-1 gap-4 sm:grid-cols-2"
        footer={
          <FormFooter
            message={boundaryError ?? error ?? undefined}
            cancel={
              onCancel ? (
                <Button variant="ghost" onClick={onCancel}>
                  {t("form.cancel")}
                </Button>
              ) : null
            }
            submit={
              <Button type="submit" disabled={busy}>
                {busy ? t("actions.saving") : submitLabel}
              </Button>
            }
          />
        }
      >
        <Field label={t("form.code")} required help={t("form.codeHelp")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              disabled={!!initial?.code}
            />
          )}
        </Field>
        <Field label={t("form.name")} required>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          )}
        </Field>
        <Field label={t("form.nameAr")} help={t("form.nameArHelp")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              // The Arabic name is Arabic whatever the interface language is,
              // so the control is always RTL rather than following the page.
              dir="rtl"
              lang="ar"
              value={nameAr ?? ""}
              onChange={(e) => setNameAr(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("form.description")} className="sm:col-span-2">
          {(props) => (
            <textarea
              {...props}
              className={FIELD_CONTROL_CLASS}
              rows={2}
              value={description ?? ""}
              onChange={(e) => setDescription(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("form.descriptionAr")} className="sm:col-span-2">
          {(props) => (
            <textarea
              {...props}
              className={FIELD_CONTROL_CLASS}
              rows={2}
              dir="rtl"
              lang="ar"
              value={descriptionAr ?? ""}
              onChange={(e) => setDescriptionAr(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("form.country")}>
          {(props) => (
            <select
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={country ?? ""}
              onChange={(e) => setCountry(e.target.value)}
            >
              <option value="">{t("form.countryNone")}</option>
              {countries.map((c) => (
                <option key={c.code} value={c.code}>
                  {isAr ? c.name_ar : c.name_en}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("form.governorate")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={governorate ?? ""}
              onChange={(e) => setGovernorate(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("form.district")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={district ?? ""}
              onChange={(e) => setDistrict(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("form.nearestCity")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={nearestCity ?? ""}
              onChange={(e) => setNearestCity(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("form.addressLine")}>
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={addressLine ?? ""}
              onChange={(e) => setAddressLine(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("form.farmType")}>
          {(props) => (
            <select
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={farmType}
              onChange={(e) => setFarmType(e.target.value as FarmType)}
            >
              {FARM_TYPES.map((v) => (
                <option key={v} value={v}>
                  {t(`farmType.${v}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("form.ownershipType")}>
          {(props) => (
            <select
              {...props}
              className={FIELD_CONTROL_CLASS}
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
          )}
        </Field>
        <Field label={t("form.primaryWaterSource")}>
          {(props) => (
            <select
              {...props}
              className={FIELD_CONTROL_CLASS}
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
          )}
        </Field>
        <Field label={t("form.establishedDate")}>
          {(props) => (
            <input
              {...props}
              type="date"
              className={FIELD_CONTROL_CLASS}
              value={established ?? ""}
              onChange={(e) => setEstablished(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("form.tags")} help={t("form.tagsHelp")} className="sm:col-span-2">
          {(props) => (
            <input
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={tags}
              onChange={(e) => setTags(e.target.value)}
            />
          )}
        </Field>
      </Card>

      <Card title={t("form.boundary")}>
        <p className="text-sm text-ap-muted">{t("form.boundaryHelp")}</p>
        <div className="mt-4">
          <MapDraw onChange={setDrawnPolygon} />
        </div>
        <div className="mt-4">
          <AoiUploader
            onFeaturesParsed={(features) => setUploadedBoundary(singleBoundary(features))}
          />
        </div>
      </Card>
    </form>
  );
}
