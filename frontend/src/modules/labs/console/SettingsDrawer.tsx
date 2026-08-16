// Farm-level configuration for Farm Console v2 — rare, manager-only, and
// deliberately one quiet entry point off the daily surface.
//
// This file is CHROME ONLY — tabs and the slide-over. Every panel is imported
// from the live modules, including the farm tab itself.
//
// It used to carry a transcribed copy of mapnext's private FarmEditTab, and
// that copy is precisely how the two consoles drifted: farm subscriptions and
// the farm-level cell size were added to one side and not the other, with
// nothing failing to make it visible. Do not re-inline a panel here.
import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { BlockDefaultsPanel } from "../mapnext/BlockDefaultsPanel";
import { FarmSettingsTab } from "../mapnext/FarmSettingsTab";
import { FarmMembersTab } from "../map/FarmMembersTab";
import { CONSOLE_QK, isConsoleQueryKey } from "./constants";

type SettingsTab = "defaults" | "members" | "farm";

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
  const navigate = useNavigate();
  const qc = useQueryClient();
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
            <FarmSettingsTab
              farmId={farmId}
              farmName={farmName}
              canInactivate={canInactivate}
              onInactivateFarm={onInactivateFarm}
              onReactivateFarm={onReactivateFarm}
              reactivating={reactivating}
              reactivateError={reactivateError}
              onEditAoi={() => navigate(`/labs/map-legacy/${farmId}`)}
              farmQueryKey={CONSOLE_QK.farm(farmId)}
              onSaved={() =>
                void qc.invalidateQueries({ predicate: (q) => isConsoleQueryKey(q.queryKey) })
              }
            />
          ) : null}
          {tab === "defaults" ? <BlockDefaultsPanel farmId={farmId} farmName={farmName} /> : null}
          {tab === "members" ? <FarmMembersTab farmId={farmId} /> : null}
        </div>
      </aside>
    </>
  );
}
