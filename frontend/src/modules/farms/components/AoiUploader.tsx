import { useState } from "react";
import { useTranslation } from "react-i18next";

import { parseAoiFile, pickPolygonalFeatures, AoiParseError } from "@/lib/aoi/parse";
import type { PolygonalFeature } from "@/lib/aoi/parse";

interface Props {
  onFeaturesParsed: (features: PolygonalFeature[]) => void;
  /**
   * Accept several files at once. Their shapes are joined in file order; a
   * shape with no name of its own takes its file's name.
   */
  multiple?: boolean;
}

function fileBaseName(name: string): string {
  return name.replace(/\.[^.]+$/, "");
}

export function AoiUploader({ onFeaturesParsed, multiple = false }: Props): JSX.Element {
  const { t } = useTranslation("farms");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [features, setFeatures] = useState<PolygonalFeature[]>([]);

  const message = (err: unknown): string => {
    if (err instanceof AoiParseError) {
      if (err.code === "too_large") return t("aoi.tooLarge");
      if (err.code === "unsupported_extension") return t("aoi.unsupported");
      if (err.code === "empty") return t("aoi.empty");
    }
    return t("aoi.invalid");
  };

  const handleFiles = async (files: File[]): Promise<void> => {
    setError(null);
    setPending(true);
    setFeatures([]);
    const all: PolygonalFeature[] = [];
    const problems: string[] = [];
    try {
      for (const file of files) {
        try {
          const result = await parseAoiFile(file);
          const polys = pickPolygonalFeatures(result.collection);
          if (polys.length === 0) throw new AoiParseError("empty", file.name);
          for (const p of polys) {
            const props = (p.properties ?? {}) as Record<string, unknown>;
            const named = [props.name, props.Name, props.NAME, props.title].some(
              (v) => typeof v === "string" && v.trim(),
            );
            all.push(
              multiple && !named
                ? { ...p, properties: { ...props, name: fileBaseName(file.name) } }
                : p,
            );
          }
        } catch (err) {
          problems.push(files.length > 1 ? `${file.name}: ${message(err)}` : message(err));
        }
      }
      if (problems.length > 0) setError(problems.join(" "));
      if (all.length > 0) {
        setFeatures(all);
        onFeaturesParsed(all);
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
        className="block cursor-pointer rounded-md border border-dashed border-ap-line p-4 text-center text-sm text-ap-muted hover:border-ap-primary hover:bg-ap-primary-soft"
      >
        {pending ? t("actions.saving") : t("aoi.drop")}
      </label>
      <input
        id="aoi-file"
        type="file"
        multiple={multiple}
        accept=".geojson,.json,.zip,.kml,application/geo+json,application/json,application/zip,application/vnd.google-earth.kml+xml"
        className="sr-only"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          // Clear it, so choosing the same file again fires a change.
          event.target.value = "";
          if (files.length > 0) void handleFiles(multiple ? files : files.slice(0, 1));
        }}
      />
      {error ? (
        <p role="alert" className="mt-2 text-sm text-ap-crit">
          {error}
        </p>
      ) : null}
      {features.length > 0 ? (
        <p className="mt-2 text-sm text-ap-muted">
          {t("aoi.pickFeature")} {features.length}
        </p>
      ) : null}
    </div>
  );
}
