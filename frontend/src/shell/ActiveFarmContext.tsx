import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { getFarm } from "@/api/farms";
import { useActiveFarmId } from "@/hooks/useActiveFarm";

/**
 * Compact farm-context strip in the shell header, sitting right
 * after the FarmSwitcher. Surfaces the bits of the active farm an
 * operator needs at-a-glance no matter which page they're on:
 *
 *   area (in the FARM'S area_unit — not hardcoded "ha"),
 *   governorate, farm_type, active/inactive status.
 *
 * Replaces the page-local FarmSummaryStrip that lived on the Labs
 * map page (now removed in the Farm-Management redesign).
 */
export function ActiveFarmContext(): ReactNode {
  const farmId = useActiveFarmId();
  const { data: farm } = useQuery({
    queryKey: ["farms", "detail", farmId] as const,
    queryFn: () => getFarm(farmId!),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
  if (!farm) return null;

  // farm.area_value is already in farm.area_unit (feddan / acre /
  // hectare); the backend stores both the canonical m² and the
  // operator's chosen unit value. No client-side conversion.
  const areaText = `${Number(farm.area_value ?? 0).toFixed(1)} ${farm.area_unit}`;

  return (
    <div className="flex min-w-0 items-center gap-2 text-[11px] text-ap-muted">
      <span aria-hidden="true" className="text-ap-line">
        ·
      </span>
      <span className="tabular-nums">{areaText}</span>
      {farm.governorate ? <span className="truncate">{farm.governorate}</span> : null}
      <span className="truncate">{farm.farm_type}</span>
      {farm.is_active ? (
        <span className="rounded bg-ap-primary-soft px-1.5 py-0.5 text-[10px] font-medium text-ap-primary">
          Active
        </span>
      ) : (
        <span className="rounded bg-ap-warn-soft px-1.5 py-0.5 text-[10px] font-medium text-ap-warn">
          Inactive
        </span>
      )}
    </div>
  );
}
