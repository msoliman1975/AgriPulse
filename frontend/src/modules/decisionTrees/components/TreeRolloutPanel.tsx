// How this tenant runs one tree: on how many farms, at which version, and
// whether that version is held.
//
// Three controls that used to have no home. Enablement existed per farm, on
// the farm's own settings tab, so turning a tree off across a fleet meant
// visiting every farm. Version pinning did not exist at all — a platform
// publish reached every tenant at the next sweep and nothing could hold it.
// Copying did not exist either, so a tenant who wanted one threshold changed
// had to ask a developer.
//
// The panel is tenant-only. A platform caller has no farms to enable a tree
// on and no pin to hold, and the API refuses all three.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { DecisionTreeVersion } from "@/api/decisionTrees";
import { Card } from "@/components/Card";
import { Skeleton } from "@/components/Skeleton";
import {
  useDecisionTreeAvailability,
  useSetDecisionTreeEnabled,
  useSetDecisionTreeVersionPin,
} from "@/queries/decisionTrees";

interface TreeRolloutPanelProps {
  code: string;
  canManage: boolean;
  /** Published versions, newest first — the only ones a pin may name. */
  versions: readonly DecisionTreeVersion[];
  /** Offered only on a platform tree; a tenant's own tree is already theirs. */
  onCopy?: () => void;
}

export function TreeRolloutPanel({
  code,
  canManage,
  versions,
  onCopy,
}: TreeRolloutPanelProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const q = useDecisionTreeAvailability(code);
  const setEnabled = useSetDecisionTreeEnabled();
  const setPin = useSetDecisionTreeVersionPin();
  const [pinChoice, setPinChoice] = useState<string>("");

  if (q.isLoading) {
    return (
      <Card noPadding className="flex flex-col gap-3 p-4">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-20 w-full" />
      </Card>
    );
  }
  if (q.isError || !q.data) {
    return (
      <Card noPadding className="p-4 text-sm text-ap-crit">
        {t("rollout.loadFailed")}
      </Card>
    );
  }

  const a = q.data;
  const publishable = versions.filter((v) => v.published_at != null);
  const selectedPin = pinChoice !== "" ? pinChoice : (a.pinned_version?.toString() ?? "");

  return (
    <Card noPadding className="flex flex-col gap-3 p-4">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ap-ink">{t("rollout.heading")}</h2>
        {onCopy && canManage ? (
          <button
            type="button"
            onClick={onCopy}
            className="rounded-md border border-ap-line px-2 py-1 text-xs text-ap-ink hover:bg-ap-line/40"
          >
            {t("rollout.copyButton")}
          </button>
        ) : null}
      </header>

      {/* --- Farms ------------------------------------------------------ */}
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-ap-muted">
            {t("rollout.farmsRunning", { running: a.farms_running, total: a.farms_total })}
          </span>
          {canManage ? (
            <button
              type="button"
              disabled={setEnabled.isPending || a.farms_total === 0}
              onClick={() => setEnabled.mutate({ code, enabled: !(a.farms_running > 0) })}
              className="rounded-md border border-ap-line px-2 py-1 text-xs text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
            >
              {a.farms_running > 0 ? t("rollout.disableAll") : t("rollout.enableAll")}
            </button>
          ) : null}
        </div>
        {/* Say the thing that would otherwise be rediscovered as a bug.
            Enablement is farm rows, and a farm created later has none, so it
            runs the tree. Cards will appear from a tree the tenant turned
            off, and without this line nothing would explain why. */}
        {a.farms_running === 0 && a.farms_total > 0 ? (
          <p className="text-[11px] leading-snug text-ap-muted">{t("rollout.newFarmsNote")}</p>
        ) : null}
        {setEnabled.isError ? (
          <p className="text-xs text-ap-crit">{t("rollout.enableFailed")}</p>
        ) : null}
      </div>

      {/* --- Version ---------------------------------------------------- */}
      <div className="flex flex-col gap-1.5 border-t border-ap-line pt-3">
        <span className="text-xs text-ap-muted">
          {a.pinned_version != null
            ? t("rollout.pinnedAt", { version: a.pinned_version })
            : t("rollout.followingCurrent", { version: a.current_version ?? "—" })}
        </span>
        {canManage ? (
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor={`pin-${code}`}>
              {t("rollout.pinLabel")}
            </label>
            <select
              id={`pin-${code}`}
              value={selectedPin}
              onChange={(e) => setPinChoice(e.target.value)}
              className="rounded-md border border-ap-line bg-ap-surface px-2 py-1 text-xs text-ap-ink"
            >
              <option value="">{t("rollout.followCurrent")}</option>
              {publishable.map((v) => (
                <option key={v.version} value={v.version}>
                  {t("rollout.versionOption", { version: v.version })}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={setPin.isPending}
              onClick={() =>
                setPin.mutate({
                  code,
                  version: selectedPin === "" ? null : Number(selectedPin),
                })
              }
              className="rounded-md border border-ap-line px-2 py-1 text-xs text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
            >
              {t("rollout.applyPin")}
            </button>
          </div>
        ) : null}
        {setPin.isError ? <p className="text-xs text-ap-crit">{t("rollout.pinFailed")}</p> : null}
      </div>
    </Card>
  );
}
