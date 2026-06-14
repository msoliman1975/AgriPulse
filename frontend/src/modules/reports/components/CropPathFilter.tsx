import { useEffect, useState, type ReactNode } from "react";
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
  /** Current path prefix (e.g. "mango.alphonso"); null = no filter. */
  value: string | null;
  /** Emits the resolved path prefix, or null when cleared back to "all". */
  onChange: (cropPath: string | null) => void;
}

/**
 * Cascading crop → variety → strain selector that emits a hierarchical
 * path *prefix* for report filtering. The user can stop at any level:
 * picking only a crop yields "mango" (all varieties/strains), adding a
 * variety yields "mango.alphonso", adding a strain yields the exact
 * "mango.alphonso.short". The variety/strain selects appear only as deep
 * as the crop's classification_depth allows.
 */
export function CropPathFilter({ value, onChange }: Props): ReactNode {
  const { t, i18n } = useTranslation("reports");
  const [crops, setCrops] = useState<Crop[]>([]);
  const [varieties, setVarieties] = useState<CropVariety[]>([]);
  const [strains, setStrains] = useState<CropVarietyStrain[]>([]);

  // Local selection by id. The emitted value is derived from the deepest
  // selected level's path (crop uses its code as the 1-segment path).
  const [cropId, setCropId] = useState<string | null>(null);
  const [varietyId, setVarietyId] = useState<string | null>(null);
  const [strainId, setStrainId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCrops()
      .then((data) => {
        if (!cancelled) setCrops(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // Reset local selection when the filter is cleared from outside.
  useEffect(() => {
    if (value === null) {
      setCropId(null);
      setVarietyId(null);
      setStrainId(null);
    }
  }, [value]);

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
    if (!varietyId) {
      setStrains([]);
      return;
    }
    listVarietyStrains(varietyId)
      .then((data) => {
        if (!cancelled) setStrains(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [varietyId]);

  const isAr = i18n.language === "ar";
  const cropLabel = (c: Crop): string => (isAr ? c.name_ar || c.name_en : c.name_en);
  const varietyLabel = (v: CropVariety): string => (isAr ? (v.name_ar ?? v.name_en) : v.name_en);
  const strainLabel = (s: CropVarietyStrain): string =>
    isAr ? (s.name_ar ?? s.name_en) : s.name_en;

  const selectedCrop = crops.find((c) => c.id === cropId) ?? null;
  const depth = selectedCrop?.classification_depth ?? "crop_only";
  const showVariety = depth === "variety" || depth === "variety_strain";
  const showStrain = depth === "variety_strain";

  const handleCrop = (id: string | null): void => {
    setCropId(id);
    setVarietyId(null);
    setStrainId(null);
    const crop = crops.find((c) => c.id === id);
    onChange(crop ? crop.code : null);
  };

  const handleVariety = (id: string | null): void => {
    setVarietyId(id);
    setStrainId(null);
    const variety = varieties.find((v) => v.id === id);
    // Drop back to the crop-level prefix when "all varieties" is picked.
    onChange(variety ? variety.path : selectedCrop ? selectedCrop.code : null);
  };

  const handleStrain = (id: string | null): void => {
    setStrainId(id);
    const strain = strains.find((s) => s.id === id);
    const variety = varieties.find((v) => v.id === varietyId);
    onChange(
      strain ? strain.path : variety ? variety.path : selectedCrop ? selectedCrop.code : null,
    );
  };

  return (
    <div className="print-hide flex flex-wrap items-center gap-2">
      <span className="label mb-0">{t("filter.crop")}</span>
      <select
        className="input w-auto"
        value={cropId ?? ""}
        onChange={(e) => handleCrop(e.target.value || null)}
        aria-label={t("filter.crop")}
      >
        <option value="">{t("filter.allCrops")}</option>
        {crops.map((c) => (
          <option key={c.id} value={c.id}>
            {cropLabel(c)}
          </option>
        ))}
      </select>
      {showVariety ? (
        <select
          className="input w-auto"
          value={varietyId ?? ""}
          onChange={(e) => handleVariety(e.target.value || null)}
          disabled={varieties.length === 0}
          aria-label={t("filter.variety")}
        >
          <option value="">{t("filter.allVarieties")}</option>
          {varieties.map((v) => (
            <option key={v.id} value={v.id}>
              {varietyLabel(v)}
            </option>
          ))}
        </select>
      ) : null}
      {showStrain ? (
        <select
          className="input w-auto"
          value={strainId ?? ""}
          onChange={(e) => handleStrain(e.target.value || null)}
          disabled={!varietyId || strains.length === 0}
          aria-label={t("filter.strain")}
        >
          <option value="">{t("filter.allStrains")}</option>
          {strains.map((s) => (
            <option key={s.id} value={s.id}>
              {strainLabel(s)}
            </option>
          ))}
        </select>
      ) : null}
      {value ? (
        <span className="font-mono text-[11px] text-ap-primary" title={t("filter.activePath")}>
          {value}
        </span>
      ) : null}
    </div>
  );
}
