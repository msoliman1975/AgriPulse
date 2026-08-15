import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { THERMAL_NATIVE_RESOLUTION_M, thermalConfidence } from "@/lib/thermalResolution";

interface Props {
  /**
   * Area the reading covers, in hectares. Omit for a farm-wide reading,
   * which is the scale this data is honest at and needs no caveat beyond
   * the resolution itself.
   */
  areaHa?: number | null;
  className?: string;
}

/**
 * The caveat that has to travel with every thermal number.
 *
 * Thermal is sensed at 100 m and delivered on a 30 m grid, so a block
 * value can look exactly as precise as a 10 m NDVI while being nothing of
 * the sort. Rendering the two side by side without saying so is the
 * failure this component exists to prevent — and it is why thermal must
 * not drive per-block irrigation volumes yet.
 */
export function ThermalResolutionNote({ areaHa, className }: Props): ReactNode {
  const { t } = useTranslation("insights");
  const confidence = thermalConfidence(areaHa);

  // No area supplied means farm scale: state the resolution, no caveat.
  const key = confidence === null ? "farm" : confidence;

  return (
    <p
      className={
        "text-[11px] leading-snug text-ap-muted " +
        (confidence === "subPixel" ? "text-ap-warn " : "") +
        (className ?? "")
      }
      data-testid="thermal-resolution-note"
      data-confidence={key}
    >
      {t(`trend.thermalResolution.${key}`, { metres: THERMAL_NATIVE_RESOLUTION_M })}
    </p>
  );
}
