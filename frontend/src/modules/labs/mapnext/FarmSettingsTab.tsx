// The Farm tab of the settings drawer, shared by BOTH consoles.
//
// It used to be a private `FarmEditTab` inside FarmConsolePage.tsx, which the
// v2 drawer then TRANSCRIBED into its own copy. Two copies is how this tab
// lost features on one side twice over: farm-level imagery/weather
// subscriptions and the farm-level cell size were both added to v2 only, and
// an operator on the default console had no way to reach either. One
// component, mounted twice, is the only arrangement that cannot drift.
//
// Order is deliberate — read top to bottom it is "what this farm IS", then
// "what it collects", then "how it is divided", then the actions:
//
//   1. Farm details      the farm's own fields          (saved by the button)
//   2. Imagery           per-farm imagery subscriptions (saves on change)
//   3. Weather           per-farm weather subscriptions (saves on change)
//   4. Zones             sub-block cell size + anomaly  (own confirm step)
//   5. Decision trees    which trees run on this farm            (saves on change)
//   6. Actions           Save farm details, Edit AoI, then the danger zone
//
// The save button sits at the bottom but belongs ONLY to section 1, and says
// so. Sections 2-4 write immediately and own their own feedback — that is the
// point of them, see FarmSubscriptionsPanel's header. A bare "Save" under all
// four would promise to save three things it cannot touch, so the label names
// its scope and each live section is marked as applying on change.
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getFarm, updateFarm, type FarmUpdatePayload, type WaterSource } from "@/api/farms";

import { FarmDecisionTreesPanel } from "./FarmDecisionTreesPanel";
import { FarmSubscriptionsPanel } from "./FarmSubscriptionsPanel";
import { FarmZonesPanel } from "./FarmZonesPanel";
import { inputCls } from "./ui";

const WATER_SOURCES: WaterSource[] = ["well", "canal", "nile", "desalinated", "rainfed", "mixed"];

// The details form lives in section 1 while its submit button lives in the
// action bar at the bottom, so they are joined by id rather than nesting.
// Nesting the live panels inside the form instead would put their number
// inputs in submit range — Enter in a cadence box would save the farm.
const DETAILS_FORM_ID = "farm-details-form";

const sectionCls = "rounded-xl border border-ap-line bg-ap-bg/40 p-4";

export interface FarmSettingsTabProps {
  farmId: string;
  farmName: string;
  canInactivate: boolean;
  onInactivateFarm: () => void;
  onReactivateFarm: () => void;
  reactivating: boolean;
  reactivateError: string | null;
  /** Where "Edit AoI" goes. The two consoles deep-link to the same legacy map. */
  onEditAoi?: () => void;
  /**
   * The host console's cache wiring. These are NOT shared: the default console
   * keys its farm query `["labs/mapnext/farm", id]` while v2 uses
   * `CONSOLE_QK.farm(id)` and invalidates by predicate. Taking both as props
   * is what lets one component serve both without a save going stale on one
   * side — the failure the transcribed copy was hiding.
   */
  farmQueryKey: readonly unknown[];
  /** Invalidate whatever else the host renders from the farm. */
  onSaved?: () => void;
}

export function FarmSettingsTab({
  farmId,
  farmName,
  canInactivate,
  onInactivateFarm,
  onReactivateFarm,
  reactivating,
  reactivateError,
  onEditAoi,
  farmQueryKey,
  onSaved,
}: FarmSettingsTabProps): ReactNode {
  const { t } = useTranslation("farmConsole");
  // Label wording reused from the farm edit form so the two agree.
  const { t: tf } = useTranslation("farms");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const farmQ = useQuery({
    queryKey: farmQueryKey,
    queryFn: () => getFarm(farmId),
    staleTime: 30_000,
  });
  const [form, setForm] = useState<FarmUpdatePayload | null>(null);
  const f = farmQ.data;
  const state: FarmUpdatePayload =
    form ??
    (f
      ? {
          name: f.name,
          name_ar: f.name_ar,
          description_ar: f.description_ar,
          governorate: f.governorate,
          district: f.district,
          nearest_city: f.nearest_city,
          primary_water_source: f.primary_water_source,
          tags: f.tags,
        }
      : {});
  const set = (patch: Partial<FarmUpdatePayload>) => setForm({ ...state, ...patch });
  const mut = useMutation({
    mutationFn: (patch: FarmUpdatePayload) => updateFarm(farmId, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: farmQueryKey });
      onSaved?.();
    },
  });

  if (farmQ.isLoading) return <div className="text-sm text-ap-muted">{t("inspector.loading")}</div>;
  if (farmQ.isError || !f)
    return <div className="text-sm text-ap-crit">{t("manage.editLoadError")}</div>;

  return (
    <div className="space-y-5">
      {/* 1 — Farm details */}
      <section className={sectionCls}>
        <h3 className="mb-1 text-sm font-bold text-ap-ink">{t("settingsFarm.detailsTitle")}</h3>
        <p className="mb-3 text-xs text-ap-muted">{t("settingsFarm.detailsHint")}</p>
        <form
          id={DETAILS_FORM_ID}
          onSubmit={(e) => {
            e.preventDefault();
            mut.mutate(state);
          }}
        >
          <label className="mb-3 block">
            <span className="mb-1 block text-xs font-semibold text-ap-muted">
              {t("settingsFarm.name")}
            </span>
            <input
              className={inputCls}
              value={state.name ?? ""}
              onChange={(e) => set({ name: e.target.value })}
            />
          </label>
          <label className="mb-1 block">
            <span className="mb-1 block text-xs font-semibold text-ap-muted">
              {tf("form.nameAr")}
            </span>
            <input
              className={inputCls}
              dir="rtl"
              value={state.name_ar ?? ""}
              onChange={(e) => set({ name_ar: e.target.value || null })}
            />
          </label>
          <p className="mb-3 text-xs text-ap-muted">{tf("form.nameArHelp")}</p>
          <label className="mb-3 block">
            <span className="mb-1 block text-xs font-semibold text-ap-muted">
              {tf("form.descriptionAr")}
            </span>
            <textarea
              className={inputCls}
              dir="rtl"
              rows={2}
              value={state.description_ar ?? ""}
              onChange={(e) => set({ description_ar: e.target.value || null })}
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="mb-3 block">
              <span className="mb-1 block text-xs font-semibold text-ap-muted">
                {t("settingsFarm.governorate")}
              </span>
              <input
                className={inputCls}
                value={state.governorate ?? ""}
                onChange={(e) => set({ governorate: e.target.value || null })}
              />
            </label>
            <label className="mb-3 block">
              <span className="mb-1 block text-xs font-semibold text-ap-muted">
                {t("settingsFarm.district")}
              </span>
              <input
                className={inputCls}
                value={state.district ?? ""}
                onChange={(e) => set({ district: e.target.value || null })}
              />
            </label>
            <label className="mb-3 block">
              <span className="mb-1 block text-xs font-semibold text-ap-muted">
                {t("settingsFarm.city")}
              </span>
              <input
                className={inputCls}
                value={state.nearest_city ?? ""}
                onChange={(e) => set({ nearest_city: e.target.value || null })}
              />
            </label>
            <label className="mb-3 block">
              <span className="mb-1 block text-xs font-semibold text-ap-muted">
                {t("settingsFarm.water")}
              </span>
              <select
                className={inputCls}
                value={state.primary_water_source ?? ""}
                onChange={(e) =>
                  set({ primary_water_source: (e.target.value || null) as WaterSource | null })
                }
              >
                <option value="">—</option>
                {WATER_SOURCES.map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-xs font-semibold text-ap-muted">
              {t("manage.tags")}
            </span>
            <input
              className={inputCls}
              value={(state.tags ?? []).join(", ")}
              onChange={(e) =>
                set({
                  tags: e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
        </form>
      </section>

      {/* 2 + 3 — Imagery and Weather, one section each, both saving on change */}
      <FarmSubscriptionsPanel farmId={farmId} />

      {/* 4 — Zones: sub-block cell size lives here, at the FARM level. It was
          reachable only from the v2 console before, which is why "where do I
          set cell size?" had no answer on the default one. */}
      <FarmZonesPanel farmId={farmId} farmName={farmName} />

      {/* 5 — Decision trees: which of them run on this farm. Sits after the
          data sections because it is a choice ABOUT that data, and it saves
          on change like the three above it. */}
      <FarmDecisionTreesPanel farmId={farmId} />

      {/* 6 — Actions. Save belongs to section 1 only; its label says so. */}
      {mut.isError ? <div className="text-xs text-ap-crit">{t("manage.saveError")}</div> : null}
      <div className="flex items-center gap-2 border-t border-ap-line pt-4">
        <button
          type="submit"
          form={DETAILS_FORM_ID}
          disabled={mut.isPending}
          className="h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white disabled:opacity-60"
        >
          {mut.isPending ? t("manage.saving") : t("settingsFarm.saveDetails")}
        </button>
        {mut.isSuccess && !form ? (
          <span className="text-xs text-ap-good">{t("settingsFarm.saved")}</span>
        ) : null}
        <button
          type="button"
          onClick={() => (onEditAoi ? onEditAoi() : navigate(`/labs/map-legacy/${farmId}`))}
          className="ms-auto text-xs text-ap-muted underline hover:text-ap-ink"
        >
          {t("settingsFarm.editAoi")}
        </button>
      </div>

      {/* Danger zone — soft inactivation (no hard delete exists by design), and
          the way back for an already-inactive farm. type="button" throughout,
          so none of it can submit the details form. */}
      {canInactivate ? (
        <section className="rounded-xl border border-ap-crit/40 bg-ap-crit/5 p-4">
          <h3 className="text-sm font-bold text-ap-crit">{t("dangerZone.title")}</h3>
          <p className="mt-1 text-xs leading-relaxed text-ap-muted">
            {t("dangerZone.inactivateHint")}
          </p>
          {f.is_active ? (
            <button
              type="button"
              onClick={onInactivateFarm}
              className="mt-3 h-9 rounded-lg border border-ap-crit px-3.5 text-sm font-semibold text-ap-crit hover:bg-ap-crit hover:text-white"
            >
              {t("dangerZone.inactivateFarm")}
            </button>
          ) : (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold text-ap-ink">
                {t("dangerZone.inactiveSince", { date: f.active_to ?? "—" })}
              </span>
              <button
                type="button"
                onClick={onReactivateFarm}
                disabled={reactivating}
                className="h-9 rounded-lg bg-ap-primary px-3.5 text-sm font-semibold text-white disabled:opacity-60"
              >
                {reactivating ? t("dangerZone.reactivating") : t("dangerZone.reactivate")}
              </button>
            </div>
          )}
          {reactivateError ? (
            <div className="mt-2 text-xs text-ap-crit">{reactivateError}</div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
