import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { getBlockCropAttributes } from "@/api/cropAssignments";

import { formatValue, label } from "./cropAttributeForm";

/**
 * Crop-attribute values as `[label, value]` pairs, for the Farm Console's
 * read-only "Crop & plan" column.
 *
 * The editor lives three clicks away under Manage → Crop, which is the right
 * home for *editing* but the wrong one for *seeing*: a user checking what a
 * block is planted with looks at the Field tab, and establishment method or
 * transplant date being absent there made the whole feature look unshipped.
 *
 * Shares the editor's query key, so opening Manage → Crop after viewing the
 * summary costs no extra request (and a save updates both).
 *
 * Returns **only attributes that hold a value** — a block with none adds no
 * rows at all, so crops outside the seeded set look exactly as they do today.
 */
export function useCropAttributeRows(blockCropId: string | null): [ReactNode, ReactNode][] {
  const { i18n } = useTranslation("farms");
  const lang = i18n.language;

  const query = useQuery({
    queryKey: ["crop_attributes", blockCropId] as const,
    queryFn: () => getBlockCropAttributes(blockCropId as string),
    enabled: blockCropId !== null,
    staleTime: 60_000,
  });

  return useMemo(() => {
    const data = query.data;
    if (!data) return [];
    const rows: [ReactNode, ReactNode][] = [];
    for (const def of data.definitions) {
      const value = data.values[def.code];
      if (value === undefined || value === null || value === "") continue;
      if (Array.isArray(value) && value.length === 0) continue;
      const unit = lang.startsWith("ar") ? def.unit_ar : def.unit_en;
      rows.push([
        label(def, lang),
        <>
          {formatValue(value, def, lang)}
          {unit ? <span className="ms-1 font-normal text-ap-muted">{unit}</span> : null}
        </>,
      ]);
    }
    return rows;
  }, [query.data, lang]);
}
