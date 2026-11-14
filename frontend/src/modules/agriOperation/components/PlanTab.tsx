// Plan tab: the farm's saved plans, and the wizard that creates or edits one.
// Phones get the saved plans read-only (decision G3); editing is on desktop.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { SavedPlan } from "@/api/agriOperation";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { queryState, resolveErrorMessage } from "@/components/asyncState";
import { useIsMobile } from "@/hooks/useIsMobile";
import { localizedField, localizedName } from "@/lib/localizedField";
import {
  useDeleteSavedPlan,
  useFarmManual,
  useManualChanges,
  useSavedPlans,
} from "@/queries/agriOperation";
import { useCapability } from "@/rbac/useCapability";
import { draftFromSaved, emptyDraft, type PlanDraft } from "../lib/planDraft";
import { PlanWizard } from "./PlanWizard";

interface PlanTabProps {
  farmId: string;
  manualId: string | null;
  onPickManual: () => void;
}

export function PlanTab({ farmId, manualId, onPickManual }: PlanTabProps): ReactNode {
  const { t } = useTranslation("agriOperation");
  const isMobile = useIsMobile();
  const canManage = useCapability("plan_allocation.manage", { farmId });
  const saved = useSavedPlans(farmId);
  const [draft, setDraft] = useState<PlanDraft | null>(null);
  const editable = canManage && !isMobile;

  if (draft) {
    return (
      <WizardForDraft
        farmId={farmId}
        draft={draft}
        onDraftChange={setDraft}
        onDone={() => setDraft(null)}
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {isMobile ? <StatusBanner kind="info">{t("plan.phoneReadOnly")}</StatusBanner> : null}
      {editable ? (
        <Card className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-ap-ink">
            {manualId ? t("plan.startHint") : t("plan.pickFirst")}
          </p>
          {manualId ? (
            <Button onClick={() => setDraft(emptyDraft(manualId))}>{t("plan.start")}</Button>
          ) : (
            <Button variant="secondary" onClick={onPickManual}>
              {t("plan.goCatalog")}
            </Button>
          )}
        </Card>
      ) : null}
      <AsyncBoundary state={queryState(saved)} empty={<EmptyState message={t("plan.noSaved")} />}>
        {(plans) => (
          <Card noPadding title={t("plan.savedTitle")}>
            <ul>
              {plans.map((p) => (
                <SavedPlanRow
                  key={p.id}
                  farmId={farmId}
                  plan={p}
                  editable={editable}
                  onEdit={() => setDraft(draftFromSaved(p))}
                />
              ))}
            </ul>
          </Card>
        )}
      </AsyncBoundary>
    </div>
  );
}

function WizardForDraft({
  farmId,
  draft,
  onDraftChange,
  onDone,
}: {
  farmId: string;
  draft: PlanDraft;
  onDraftChange: (d: PlanDraft) => void;
  onDone: () => void;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const manual = useFarmManual(farmId, draft.templateId);
  return (
    <AsyncBoundary
      state={queryState(manual)}
      isEmpty={() => false}
      empty={<EmptyState message={t("catalog.empty")} />}
    >
      {(m) => (
        <div className="flex flex-col gap-3">
          <StatusBanner kind="info">
            {draft.id
              ? t("plan.editing", { name: draft.seasonLabel })
              : t("plan.allocating", { name: localizedName(i18n.language, m.name, m.name_ar) })}
          </StatusBanner>
          <PlanWizard
            farmId={farmId}
            manual={m}
            draft={draft}
            onDraftChange={onDraftChange}
            onDone={onDone}
          />
        </div>
      )}
    </AsyncBoundary>
  );
}

function SavedPlanRow({
  farmId,
  plan,
  editable,
  onEdit,
}: {
  farmId: string;
  plan: SavedPlan;
  editable: boolean;
  onEdit: () => void;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const [confirming, setConfirming] = useState(false);
  const [showChanges, setShowChanges] = useState(false);
  const del = useDeleteSavedPlan(farmId);
  const changes = useManualChanges(farmId, plan.id, showChanges);
  const manualName = plan.template_name
    ? localizedName(lang, plan.template_name, plan.template_name_ar)
    : (plan.template_code ?? "");

  return (
    <li className="flex flex-col gap-2 border-b border-ap-line px-4 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-ap-ink">{plan.season_label}</span>
        {plan.manual_updated ? <Pill kind="warn">{t("plan.manualUpdated")}</Pill> : null}
        <span className="text-xs text-ap-muted">
          {t("plan.savedMeta", {
            manual: manualName,
            blocks: plan.blocks.length,
            date: plan.updated_at.slice(0, 10),
          })}
        </span>
        <span className="flex-1" />
        {plan.manual_updated ? (
          <Button variant="ghost" size="sm" onClick={() => setShowChanges((v) => !v)}>
            {showChanges ? t("plan.hideChanges") : t("plan.reviewChanges")}
          </Button>
        ) : null}
        {editable ? (
          <>
            <Button variant="secondary" size="sm" onClick={onEdit}>
              {t("plan.edit")}
            </Button>
            {confirming ? (
              <>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={del.isPending}
                  onClick={() => del.mutate(plan.id, { onSuccess: () => setConfirming(false) })}
                >
                  {t("plan.confirmDelete")}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
                  {t("plan.cancel")}
                </Button>
              </>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
                {t("plan.delete")}
              </Button>
            )}
          </>
        ) : null}
      </div>
      {confirming ? <p className="text-xs text-ap-muted">{t("plan.deleteHint")}</p> : null}
      {del.isError ? (
        <StatusBanner kind="crit">
          {resolveErrorMessage(del.error, t("plan.deleteFailed"))}
        </StatusBanner>
      ) : null}
      {showChanges && changes.data ? (
        <div className="rounded-card bg-ap-bg p-3 text-sm text-ap-ink">
          {!changes.data.comparable ? (
            <p>{t("plan.changes.unknown")}</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {changes.data.added.map((c) => (
                <li key={`a-${c.code}`}>
                  {t("plan.changes.added", {
                    title: localizedField(lang, c.title, c.title_ar) ?? c.code,
                  })}
                </li>
              ))}
              {changes.data.removed.map((c) => (
                <li key={`r-${c.code}`}>
                  {t("plan.changes.removed", {
                    title: localizedField(lang, c.title, c.title_ar) ?? c.code,
                  })}
                </li>
              ))}
              {changes.data.changed.map((c) => (
                <li key={`c-${c.code}`}>
                  {t("plan.changes.changed", {
                    title: localizedField(lang, c.title, c.title_ar) ?? c.code,
                    fields: c.fields
                      .map((f) => t(`plan.changes.field.${f}`, { defaultValue: f }))
                      .join(", "),
                  })}
                </li>
              ))}
            </ul>
          )}
          {editable ? (
            <p className="mt-2 text-xs text-ap-muted">{t("plan.changes.howToApply")}</p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
