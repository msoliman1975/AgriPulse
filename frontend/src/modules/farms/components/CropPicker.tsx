import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { listCrops, listCropVarieties, type Crop, type CropVariety } from "@/api/crops";

interface Props {
  cropId: string | null;
  cropVarietyId: string | null;
  onChange: (cropId: string | null, cropVarietyId: string | null) => void;
}

export function CropPicker({ cropId, cropVarietyId, onChange }: Props): JSX.Element {
  const { t, i18n } = useTranslation("farms");
  const [crops, setCrops] = useState<Crop[]>([]);
  const [varieties, setVarieties] = useState<CropVariety[]>([]);

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

  const isAr = i18n.language === "ar";
  const cropLabel = (c: Crop): string => (isAr ? c.name_ar || c.name_en : c.name_en);
  const varietyLabel = (v: CropVariety): string => (isAr ? (v.name_ar ?? v.name_en) : v.name_en);

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div>
        <label className="label" htmlFor="crop-select">
          {t("block.assignCrop")}
        </label>
        <select
          id="crop-select"
          className="input"
          value={cropId ?? ""}
          onChange={(e) => onChange(e.target.value || null, null)}
        >
          <option value="">—</option>
          {crops.map((c) => (
            <option key={c.id} value={c.id}>
              {cropLabel(c)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="label" htmlFor="variety-select">
          {t("block.variety")}
        </label>
        <select
          id="variety-select"
          className="input"
          value={cropVarietyId ?? ""}
          onChange={(e) => onChange(cropId, e.target.value || null)}
          disabled={!cropId || varieties.length === 0}
        >
          <option value="">{t("block.noVariety")}</option>
          {varieties.map((v) => (
            <option key={v.id} value={v.id}>
              {varietyLabel(v)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
