import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  listCrops,
  listCropVarieties,
  listVarietyStrains,
  type Crop,
  type CropVariety,
  type CropVarietyStrain,
} from "@/api/crops";

interface Props {
  cropId: string | null;
  cropVarietyId: string | null;
  cropVarietyStrainId: string | null;
  onChange: (
    cropId: string | null,
    cropVarietyId: string | null,
    cropVarietyStrainId: string | null,
  ) => void;
  // Fires whenever the selection satisfies (or stops satisfying) the crop's
  // required classification depth, so callers can gate the submit button and
  // avoid a guaranteed 422 from the backend's exact-depth validation.
  onValidityChange?: (complete: boolean) => void;
  // The canonical crop path for the current selection ("mango.sukkary"), or
  // null until it reaches the crop's required depth. Callers need it to resolve
  // the crop's attribute definitions *before* an assignment exists — the
  // picker already holds the catalog rows, so deriving it here avoids a second
  // fetch and a second place that knows how a path is built.
  onCropPathChange?: (cropPath: string | null) => void;
}

export function CropPicker({
  cropId,
  cropVarietyId,
  cropVarietyStrainId,
  onChange,
  onValidityChange,
  onCropPathChange,
}: Props): JSX.Element {
  const { t, i18n } = useTranslation("farms");
  const [crops, setCrops] = useState<Crop[]>([]);
  const [varieties, setVarieties] = useState<CropVariety[]>([]);
  const [strains, setStrains] = useState<CropVarietyStrain[]>([]);
  const [strainsLoading, setStrainsLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listCrops()
      .then((data) => {
        if (!cancelled) setCrops(data);
      })
      .catch(() => {
        // intentionally swallow — caller's form-level error path will
        // surface the api error via the surrounding submit attempt.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!cropId) {
      setVarieties([]);
      return;
    }
    listCropVarieties(cropId)
      .then((data) => {
        if (!cancelled) setVarieties(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [cropId]);

  useEffect(() => {
    let cancelled = false;
    if (!cropVarietyId) {
      setStrains([]);
      setStrainsLoading(false);
      return;
    }
    setStrainsLoading(true);
    listVarietyStrains(cropVarietyId)
      .then((data) => {
        if (!cancelled) setStrains(data);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setStrainsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [cropVarietyId]);

  const isAr = i18n.language === "ar";
  const cropLabel = (c: Crop): string => (isAr ? c.name_ar || c.name_en : c.name_en);
  const varietyLabel = (v: CropVariety): string => (isAr ? (v.name_ar ?? v.name_en) : v.name_en);
  const strainLabel = (s: CropVarietyStrain): string =>
    isAr ? (s.name_ar ?? s.name_en) : s.name_en;

  // The selected crop's classification_depth dictates how deep the picker goes:
  // crop_only → no variety/strain, variety → variety only, variety_strain → both.
  const selectedCrop = crops.find((c) => c.id === cropId) ?? null;
  const depth = selectedCrop?.classification_depth ?? "crop_only";
  const showVariety = depth === "variety" || depth === "variety_strain";
  const showStrain = depth === "variety_strain";

  const complete =
    Boolean(cropId) &&
    (depth !== "variety" || Boolean(cropVarietyId)) &&
    (depth !== "variety_strain" || Boolean(cropVarietyId && cropVarietyStrainId));

  // Notify only when the VALUE changes, not when the callback identity does.
  //
  // Callers naturally pass an inline arrow, whose identity changes every
  // render. With the callback in the dep array that fires the effect on every
  // render, and a parent that sets state in response then re-renders — a loop
  // that silently wiped the crop-fields form on every keystroke. Comparing
  // against the last emitted value makes this safe however the caller passes
  // its handler, which is the caller's reasonable expectation.
  const lastComplete = useRef<boolean | undefined>(undefined);
  useEffect(() => {
    if (lastComplete.current === complete) return;
    lastComplete.current = complete;
    onValidityChange?.(complete);
  }, [onValidityChange, complete]);

  // `path` is denormalised onto the variety/strain rows by the catalog, so the
  // deepest selected node already carries it.
  const cropPath = !complete
    ? null
    : depth === "variety_strain"
      ? (strains.find((s) => s.id === cropVarietyStrainId)?.path ?? null)
      : depth === "variety"
        ? (varieties.find((v) => v.id === cropVarietyId)?.path ?? null)
        : (selectedCrop?.code ?? null);

  const lastCropPath = useRef<string | null | undefined>(undefined);
  useEffect(() => {
    if (lastCropPath.current === cropPath) return;
    lastCropPath.current = cropPath;
    onCropPathChange?.(cropPath);
  }, [onCropPathChange, cropPath]);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div>
        <label className="label" htmlFor="crop-select">
          {t("block.assignCrop")}
        </label>
        <select
          id="crop-select"
          className="input"
          value={cropId ?? ""}
          onChange={(e) => onChange(e.target.value || null, null, null)}
        >
          <option value="">—</option>
          {crops.map((c) => (
            <option key={c.id} value={c.id}>
              {cropLabel(c)}
            </option>
          ))}
        </select>
      </div>
      {showVariety ? (
        <div>
          <label className="label" htmlFor="variety-select">
            {t("block.variety")}
          </label>
          <select
            id="variety-select"
            className="input"
            value={cropVarietyId ?? ""}
            onChange={(e) => onChange(cropId, e.target.value || null, null)}
            disabled={varieties.length === 0}
          >
            <option value="">{t("block.noVariety")}</option>
            {varieties.map((v) => (
              <option key={v.id} value={v.id}>
                {varietyLabel(v)}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      {showStrain ? (
        <div>
          <label className="label" htmlFor="strain-select">
            {t("block.strain")}
          </label>
          <select
            id="strain-select"
            className="input"
            value={cropVarietyStrainId ?? ""}
            onChange={(e) => onChange(cropId, cropVarietyId, e.target.value || null)}
            disabled={!cropVarietyId || strains.length === 0}
          >
            <option value="">{t("block.noStrain")}</option>
            {strains.map((s) => (
              <option key={s.id} value={s.id}>
                {strainLabel(s)}
              </option>
            ))}
          </select>
          {cropVarietyId && !strainsLoading && strains.length === 0 ? (
            <p className="mt-1 text-xs text-ap-warn">{t("block.noStrainsForVariety")}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
