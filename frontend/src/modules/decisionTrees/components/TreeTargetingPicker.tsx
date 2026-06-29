// Multi-axis targeting picker for decision-tree authoring (DT targeting PR-5).
//
// Three multi-selects — crop (required), country, soil — whose values feed the
// create payload's crop_paths / country_codes / soil_textures. Crop reuses the
// cascading CropPathFilter as an "adder" so an author can target several crop
// slices (e.g. mango + citrus.valencia). Empty country/soil = "any".

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { listCountries, type Country } from "@/api/countries";
import { CropPathFilter } from "@/modules/reports/components/CropPathFilter";

// Mirrors backend farms.schemas.SoilTexture / the blocks.soil_texture CHECK.
const SOIL_TEXTURES = [
  "sandy",
  "sandy_loam",
  "loam",
  "clay_loam",
  "clay",
  "silty_loam",
  "silty_clay",
] as const;

interface Props {
  cropPaths: string[];
  countryCodes: string[];
  soilTextures: string[];
  onCropPathsChange: (next: string[]) => void;
  onCountryCodesChange: (next: string[]) => void;
  onSoilTexturesChange: (next: string[]) => void;
}

function Chips({
  values,
  onRemove,
}: {
  values: string[];
  onRemove: (v: string) => void;
}): ReactNode {
  if (values.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((v) => (
        <span
          key={v}
          className="inline-flex items-center gap-1 rounded-full bg-ap-primary/10 px-2 py-0.5 text-xs text-ap-primary"
        >
          <span className="font-mono">{v}</span>
          <button
            type="button"
            onClick={() => onRemove(v)}
            className="text-ap-primary/70 hover:text-ap-crit"
            aria-label={`remove ${v}`}
          >
            ×
          </button>
        </span>
      ))}
    </div>
  );
}

export function TreeTargetingPicker({
  cropPaths,
  countryCodes,
  soilTextures,
  onCropPathsChange,
  onCountryCodesChange,
  onSoilTexturesChange,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("decisionTrees");
  const isAr = i18n.language === "ar";
  const [pendingCrop, setPendingCrop] = useState<string | null>(null);
  const [countries, setCountries] = useState<Country[]>([]);

  useEffect(() => {
    let active = true;
    listCountries()
      .then((rows) => {
        if (active) setCountries(rows);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const addCrop = (): void => {
    if (pendingCrop && !cropPaths.includes(pendingCrop)) {
      onCropPathsChange([...cropPaths, pendingCrop]);
    }
    setPendingCrop(null);
  };

  const toggle = (list: string[], value: string, on: (n: string[]) => void): void => {
    on(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Crop — required */}
      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-ap-muted">
          {t("targeting.crop")} <span className="text-ap-crit">*</span>
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <CropPathFilter value={pendingCrop} onChange={setPendingCrop} />
          <button
            type="button"
            onClick={addCrop}
            disabled={!pendingCrop}
            className="rounded-md border border-ap-primary px-2 py-1 text-xs font-medium text-ap-primary hover:bg-ap-primary/5 disabled:opacity-50"
          >
            {t("targeting.add")}
          </button>
        </div>
        <Chips values={cropPaths} onRemove={(v) => onCropPathsChange(cropPaths.filter((c) => c !== v))} />
        {cropPaths.length === 0 ? (
          <span className="text-[11px] text-ap-muted">{t("targeting.cropRequired")}</span>
        ) : null}
      </div>

      {/* Country — optional, empty = any */}
      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-ap-muted">{t("targeting.country")}</span>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {countries.map((c) => (
            <label key={c.code} className="flex items-center gap-1.5 text-xs text-ap-ink">
              <input
                type="checkbox"
                checked={countryCodes.includes(c.code)}
                onChange={() => toggle(countryCodes, c.code, onCountryCodesChange)}
              />
              {isAr ? c.name_ar : c.name_en}
            </label>
          ))}
        </div>
        <span className="text-[11px] text-ap-muted">{t("targeting.anyHint")}</span>
      </div>

      {/* Soil — optional, empty = any */}
      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-ap-muted">{t("targeting.soil")}</span>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {SOIL_TEXTURES.map((s) => (
            <label key={s} className="flex items-center gap-1.5 text-xs text-ap-ink">
              <input
                type="checkbox"
                checked={soilTextures.includes(s)}
                onChange={() => toggle(soilTextures, s, onSoilTexturesChange)}
              />
              {t(`targeting.soilValues.${s}`)}
            </label>
          ))}
        </div>
        <span className="text-[11px] text-ap-muted">{t("targeting.anyHint")}</span>
      </div>
    </div>
  );
}
