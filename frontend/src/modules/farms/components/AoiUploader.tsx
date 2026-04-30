import { useState } from "react";
import { useTranslation } from "react-i18next";

import { parseAoiFile, pickPolygonalFeatures, AoiParseError } from "@/lib/aoi/parse";
import type { PolygonalFeature } from "@/lib/aoi/parse";

interface Props {
  onFeaturesParsed: (features: PolygonalFeature[]) => void;
}

export function AoiUploader({ onFeaturesParsed }: Props): JSX.Element {
  const { t } = useTranslation("farms");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [features, setFeatures] = useState<PolygonalFeature[]>([]);

  const handleFile = async (file: File): Promise<void> => {
    setError(null);
    setPending(true);
    setFeatures([]);
    try {
      const result = await parseAoiFile(file);
      const polys = pickPolygonalFeatures(result.collection);
      if (polys.length === 0) {
        setError(t("aoi.empty"));
        return;
      }
      setFeatures(polys);
      onFeaturesParsed(polys);
    } catch (err) {
      if (err instanceof AoiParseError) {
        if (err.code === "too_large") setError(t("aoi.tooLarge"));
        else if (err.code === "unsupported_extension") setError(t("aoi.unsupported"));
        else if (err.code === "empty") setError(t("aoi.empty"));
        else setError(t("aoi.invalid"));
      } else {
        setError(t("aoi.invalid"));
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <div>
      <label className="label">{t("aoi.uploadLabel")}</label>
      <label
        htmlFor="aoi-file"
        className="block cursor-pointer rounded-md border border-dashed border-slate-300 p-4 text-center text-sm text-slate-600 hover:border-brand-500 hover:bg-brand-50"
      >
        {pending ? t("actions.saving") : t("aoi.drop")}
      </label>
      <input
        id="aoi-file"
        type="file"
        accept=".geojson,.json,.zip,.kml,application/geo+json,application/json,application/zip,application/vnd.google-earth.kml+xml"
        className="sr-only"
        onChange={(event) => {
          const f = event.target.files?.[0];
          if (f) void handleFile(f);
        }}
      />
      {error ? (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      ) : null}
      {features.length > 0 ? (
        <p className="mt-2 text-sm text-slate-600">
          {t("aoi.pickFeature")} {features.length}
        </p>
      ) : null}
    </div>
  );
}
