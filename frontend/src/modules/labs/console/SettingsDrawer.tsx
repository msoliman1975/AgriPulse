// Farm-level configuration for Farm Console v2 — rare, manager-only, and
// deliberately one quiet entry point off the daily surface.
//
// Transcribed from modules/labs/mapnext/FarmConsolePage.tsx @ 7b7f7ba0
// (SettingsDrawer + FarmEditTab, which that file keeps private). The heavy
// panels — block defaults and members — are imported from the live modules
// unchanged, so this file is chrome plus the compact farm form.
import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getFarm, updateFarm, type FarmUpdatePayload, type WaterSource } from "@/api/farms";
import { Card } from "@/components/Card";
import { BlockDefaultsPanel } from "../mapnext/BlockDefaultsPanel";
import { FarmMembersTab } from "../map/FarmMembersTab";
import { inputCls } from "../mapnext/ui";
import { CONSOLE_QK, isConsoleQueryKey } from "./constants";

type SettingsTab = "defaults" | "members" | "farm";

const WATER_SOURCES: WaterSource[] = ["well", "canal", "nile", "desalinated", "rainfed", "mixed"];
// Reuse the console's shared input style rather than redeclaring the class
// string — that is how the legacy /farms forms drifted apart in the first
// place, and the design-system lint rule (correctly) rejects the inline copy.
const settingsInput = inputCls;

interface Props {
  farmId: string;
  farmName: string;
  canInactivate: boolean;
  onInactivateFarm: () => void;
  onReactivateFarm: () => void;
  reactivating: boolean;
  reactivateError: string | null;
  onClose: () => void;
}

export function SettingsDrawer({
  farmId,
  farmName,
  canInactivate,
  onInactivateFarm,
  onReactivateFarm,
  reactivating,
  reactivateError,
  onClose,
}: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [tab, setTab] = useState<SettingsTab>("farm");
  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "farm", label: t("settings.tabFarm") },
    { id: "defaults", label: t("settings.tabDefaults") },
    { id: "members", label: t("settings.tabMembers") },
  ];
  return (
    <>
      <button
        type="button"
        aria-label={t("dock.close")}
        className="fixed inset-0 z-[90] bg-ap-ink/30"
        onClick={onClose}
      />
      <aside className="fixed inset-y-0 end-0 z-[100] flex w-[560px] max-w-[94vw] flex-col bg-ap-panel shadow-2xl">
        <div className="flex items-center gap-3 border-b border-ap-line px-5 py-4">
          <span aria-hidden="true" className="text-xl">
            ⚙
          </span>
          <div>
            <h2 className="text-section-title font-bold text-ap-ink">{t("settings.title")}</h2>
            <div className="text-meta text-ap-muted">{farmName}</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ms-auto grid h-8 w-8 place-items-center rounded-lg text-ap-muted hover:bg-ap-line/50"
            aria-label={t("dock.close")}
          >
            ✕
          </button>
        </div>
        <div role="tablist" className="flex gap-1 border-b border-ap-line px-4 pt-2.5">
          {tabs.map((tb) => (
            <button
              key={tb.id}
              type="button"
              role="tab"
              aria-selected={tab === tb.id}
              onClick={() => setTab(tb.id)}
              className={
                "rounded-t-lg border-b-2 px-3.5 py-2 text-sm font-semibold " +
                (tab === tb.id
                  ? "border-ap-primary text-ap-primary"
                  : "border-transparent text-ap-muted hover:text-ap-ink")
              }
            >
              {tb.label}
            </button>
          ))}
        </div>
        <div className="flex-1 overflow-auto p-5">
          {tab === "farm" ? (
            <FarmEditTab
              farmId={farmId}
              canInactivate={canInactivate}
              onInactivateFarm={onInactivateFarm}
              onReactivateFarm={onReactivateFarm}
              reactivating={reactivating}
              reactivateError={reactivateError}
            />
          ) : null}
          {tab === "defaults" ? <BlockDefaultsPanel farmId={farmId} farmName={farmName} /> : null}
          {tab === "members" ? <FarmMembersTab farmId={farmId} /> : null}
        </div>
      </aside>
    </>
  );
}

function FarmEditTab({
  farmId,
  canInactivate,
  onInactivateFarm,
  onReactivateFarm,
  reactivating,
  reactivateError,
}: {
  farmId: string;
  canInactivate: boolean;
  onInactivateFarm: () => void;
  onReactivateFarm: () => void;
  reactivating: boolean;
  reactivateError: string | null;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const navigate = useNavigate();
  const qc = useQueryClient();
  const farmQ = useQuery({
    queryKey: CONSOLE_QK.farm(farmId),
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
          governorate: f.governorate,
          district: f.district,
          nearest_city: f.nearest_city,
          primary_water_source: f.primary_water_source,
          tags: f.tags,
        }
      : {});
  const set = (patch: Partial<FarmUpdatePayload>): void => setForm({ ...state, ...patch });
  const mut = useMutation({
    mutationFn: (patch: FarmUpdatePayload) => updateFarm(farmId, patch),
    onSuccess: () => {
      void qc.invalidateQueries({ predicate: (q) => isConsoleQueryKey(q.queryKey) });
    },
  });

  if (farmQ.isLoading) return <div className="text-sm text-ap-muted">{t("inspector.loading")}</div>;
  if (farmQ.isError || !f)
    return <div className="text-sm text-ap-crit">{t("manage.editLoadError")}</div>;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        mut.mutate(state);
      }}
    >
      <label className="mb-3 block">
        <span className="mb-1 block text-meta font-semibold text-ap-muted">
          {t("settingsFarm.name")}
        </span>
        <input
          className={settingsInput}
          value={state.name ?? ""}
          onChange={(e) => set({ name: e.target.value })}
        />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="mb-3 block">
          <span className="mb-1 block text-meta font-semibold text-ap-muted">
            {t("settingsFarm.governorate")}
          </span>
          <input
            className={settingsInput}
            value={state.governorate ?? ""}
            onChange={(e) => set({ governorate: e.target.value || null })}
          />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-meta font-semibold text-ap-muted">
            {t("settingsFarm.district")}
          </span>
          <input
            className={settingsInput}
            value={state.district ?? ""}
            onChange={(e) => set({ district: e.target.value || null })}
          />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-meta font-semibold text-ap-muted">
            {t("settingsFarm.city")}
          </span>
          <input
            className={settingsInput}
            value={state.nearest_city ?? ""}
            onChange={(e) => set({ nearest_city: e.target.value || null })}
          />
        </label>
        <label className="mb-3 block">
          <span className="mb-1 block text-meta font-semibold text-ap-muted">
            {t("settingsFarm.water")}
          </span>
          <select
            className={settingsInput}
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
      <label className="mb-3 block">
        <span className="mb-1 block text-meta font-semibold text-ap-muted">{t("manage.tags")}</span>
        <input
          className={settingsInput}
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
      {mut.isError ? (
        <div className="mb-2 text-meta text-ap-crit">{t("manage.saveError")}</div>
      ) : null}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={mut.isPending}
          className="h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white disabled:opacity-60"
        >
          {mut.isPending ? t("manage.saving") : t("manage.save")}
        </button>
        {mut.isSuccess && !form ? (
          <span className="text-meta text-ap-good">{t("settingsFarm.saved")}</span>
        ) : null}
        {/* The one remaining escape hatch into the legacy map: polygon
            editing has not reached the console yet. Labelled so it reads as
            a deliberate hand-off rather than a stray link. */}
        <button
          type="button"
          onClick={() => navigate(`/labs/map-legacy/${farmId}`)}
          className="ms-auto text-meta text-ap-muted underline hover:text-ap-ink"
        >
          {t("settingsFarm.editAoi")}
        </button>
      </div>

      {canInactivate ? (
        <Card className="mt-7 border-ap-crit/40 bg-ap-crit/5">
          <h3 className="text-card-title font-bold text-ap-crit">{t("dangerZone.title")}</h3>
          <p className="mt-1 text-meta leading-relaxed text-ap-muted">
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
              <span className="text-meta font-semibold text-ap-ink">
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
            <div className="mt-2 text-meta text-ap-crit">{reactivateError}</div>
          ) : null}
        </Card>
      ) : null}
    </form>
  );
}
