import { useQuery } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { getFarmSeasonContext, type SeasonContextCrop } from "@/api/insights";
import { Skeleton } from "@/components/Skeleton";
import i18n from "@/i18n";

interface Props {
  farmId: string;
  /** Selected crop ids; empty means "All". */
  selected: readonly string[];
  onChange: (next: string[]) => void;
  /** Lets the page resolve the selection to block ids as crops load. */
  onCropsLoaded?: (crops: readonly SeasonContextCrop[]) => void;
}

/**
 * "What's growing here" — and the overview's crop filter.
 *
 * The chips were read-only labels; they are now the control that narrows the
 * page's block-scoped cards to one or more crops. "All" is a real option
 * rather than an implied empty state, because a filter whose off-switch is
 * invisible is one people forget they left on.
 *
 * What it filters is deliberately partial, and the bar says so: the
 * vegetation trend, the block health scorecard and per-block disease/pest
 * risk are per-block and can be narrowed. Farm weather cannot — Open-Meteo
 * gives one centroid reading per farm, so there is no per-crop temperature.
 * Filtering it would mean showing identical numbers under a label claiming
 * they are crop-specific.
 */
export function SeasonContextBar({ farmId, selected, onChange, onCropsLoaded }: Props): ReactNode {
  const { t } = useTranslation("insights");
  const isAr = i18n.language === "ar";
  const { data, isLoading } = useQuery({
    queryKey: ["insights", "season-context", farmId] as const,
    queryFn: () => getFarmSeasonContext(farmId),
    enabled: Boolean(farmId),
    staleTime: 5 * 60_000,
  });

  const crops = data?.crops;
  useEffect(() => {
    if (crops) onCropsLoaded?.(crops);
  }, [crops, onCropsLoaded]);

  // A crop that vanished (block reassigned, farm switched) must not stay
  // latched in a selection the reader can no longer see or clear.
  useEffect(() => {
    if (!crops) return;
    const known = new Set(crops.map((c) => c.crop_id));
    const pruned = selected.filter((id) => known.has(id));
    if (pruned.length !== selected.length) onChange(pruned);
  }, [crops, selected, onChange]);

  if (isLoading) {
    return <Skeleton className="h-10 w-full rounded-md" />;
  }
  if (!data) return null;

  const hasCrops = data.crops.length > 0;
  const nameOf = (c: SeasonContextCrop): string => (isAr ? c.name_ar || c.name_en : c.name_en);
  const allActive = selected.length === 0;

  const toggle = (cropId: string): void => {
    const next = selected.includes(cropId)
      ? selected.filter((id) => id !== cropId)
      : [...selected, cropId];
    onChange(next);
  };

  return (
    <div
      role="region"
      aria-label={t("season.regionLabel")}
      className="flex flex-wrap items-center gap-2 rounded-md border border-ap-line bg-ap-bg/40 px-3 py-2 text-xs"
    >
      <span className="font-semibold text-ap-muted">{t("season.label")}</span>
      {hasCrops ? (
        <>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("season.filterLabel")}>
            <button
              type="button"
              onClick={() => onChange([])}
              aria-pressed={allActive}
              className={
                "rounded px-2 py-0.5 font-medium transition-colors " +
                (allActive
                  ? "bg-ap-primary text-white"
                  : "bg-white text-ap-ink shadow-sm hover:bg-ap-bg")
              }
            >
              {t("season.all")}
            </button>
            {data.crops.map((c) => {
              const on = selected.includes(c.crop_id);
              return (
                <button
                  key={c.crop_id}
                  type="button"
                  onClick={() => toggle(c.crop_id)}
                  aria-pressed={on}
                  className={
                    "inline-flex items-center gap-1 rounded px-1.5 py-0.5 transition-colors " +
                    (on
                      ? "bg-ap-primary text-white"
                      : "bg-white text-ap-ink shadow-sm hover:bg-ap-bg")
                  }
                >
                  <span className="font-medium">{nameOf(c)}</span>
                  <span className={on ? "text-[10px] text-white/80" : "text-[10px] text-ap-muted"}>
                    {t("season.blockCount", { count: c.block_count })}
                  </span>
                </button>
              );
            })}
          </div>
          {!allActive ? (
            <span className="text-[11px] text-ap-muted">{t("season.filterScope")}</span>
          ) : null}
        </>
      ) : (
        <span className="text-ap-muted">
          {t("season.noCrops", { count: data.active_block_count })}
        </span>
      )}
    </div>
  );
}

/** Blocks carrying any of the selected crops. An empty selection means "All",
 *  which is `null` — "every block" and "no blocks" must not collapse to the
 *  same value, or a filter matching nothing would silently show everything. */
export function blocksForCrops(
  crops: readonly SeasonContextCrop[] | undefined,
  selected: readonly string[],
): string[] | null {
  if (!crops || selected.length === 0) return null;
  const chosen = new Set(selected);
  const ids = new Set<string>();
  for (const c of crops) {
    if (!chosen.has(c.crop_id)) continue;
    for (const id of c.block_ids) ids.add(id);
  }
  return [...ids];
}
