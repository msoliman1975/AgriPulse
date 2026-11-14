// The Plan tab's four steps: blocks -> operations -> season and start dates ->
// calendar. Saving applies the plan to the blocks' Plan board.

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  previewSavedPlan,
  type AllocationApplyResult,
  type AllocationCustomActivity,
  type OperationManual,
} from "@/api/agriOperation";
import { listBlocks } from "@/api/blocks";
import { ACTIVITY_TYPES, listAppliableTemplates, type PlanActivityType } from "@/api/planTemplates";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { LinkButton } from "@/components/LinkButton";
import { StatusBanner } from "@/components/StatusBanner";
import { resolveErrorMessage } from "@/components/asyncState";
import { localizedField, localizedName } from "@/lib/localizedField";
import { useSaveSavedPlan } from "@/queries/agriOperation";
import { trackFeature } from "@/telemetry";
import { useFlow } from "@/telemetry/useFlow";
import { TYPE_CLASS } from "../lib/manualStyle";
import {
  draftProblems,
  newCustomKey,
  setOverride,
  toggleCode,
  toRequest,
  type PlanDraft,
} from "../lib/planDraft";
import { activityWeek, seasonLayout } from "../lib/weeks";
import { stageName } from "../lib/manualStyle";
import { WeekCalendar } from "./WeekCalendar";

type Step = 1 | 2 | 3 | 4;
// Step names as the telemetry taxonomy lists them (flow agri_operation_plan).
const STEP_NAMES = { 1: "blocks", 2: "operations", 3: "season", 4: "calendar" } as const;

interface PlanWizardProps {
  farmId: string;
  manual: OperationManual;
  draft: PlanDraft;
  onDraftChange: (d: PlanDraft) => void;
  onDone: () => void;
}

export function PlanWizard({
  farmId,
  manual,
  draft,
  onDraftChange,
  onDone,
}: PlanWizardProps): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const [step, setStep] = useState<Step>(1);
  const [result, setResult] = useState<AllocationApplyResult | null>(null);
  const save = useSaveSavedPlan(farmId);
  // Telemetry: how far people get through the wizard, and how often a new
  // plan or an edit is saved. No farm content travels, only step names.
  // useFlow returns a new object each render; its callbacks are stable.
  const flow = useFlow("agri_operation_plan");
  const { start: startFlow, step: stepFlow } = flow;
  const editing = Boolean(draft.id);
  useEffect(() => {
    startFlow(editing ? "edit" : "new");
  }, [startFlow, editing]);
  useEffect(() => {
    stepFlow(STEP_NAMES[step]);
  }, [stepFlow, step]);

  const blocks = useQuery({
    queryKey: ["blocks", farmId, "agri_operation"],
    queryFn: () => listBlocks(farmId, { limit: 500 }),
  });
  const appliable = useQuery({
    queryKey: ["plan_templates", "appliable", farmId],
    queryFn: () => listAppliableTemplates(farmId),
  });
  const matching = useMemo(
    () => appliable.data?.find((tpl) => tpl.id === manual.id)?.matching_blocks ?? [],
    [appliable.data, manual.id],
  );
  const blockLabel = (id: string, fallback: string | null): string => {
    const b = blocks.data?.items.find((x) => x.id === id);
    if (b) return localizedName(lang, b.name ?? b.code, b.name_ar) || b.code;
    return fallback ?? matching.find((m) => m.block_id === id)?.block_code ?? id.slice(0, 8);
  };

  const request = useMemo(() => toRequest(draft), [draft]);
  const problems = draftProblems(draft);
  const preview = useQuery({
    queryKey: ["agri_operation", "preview", farmId, request],
    queryFn: () => previewSavedPlan(farmId, request),
    enabled: step === 4 && problems.length === 0,
    placeholderData: keepPreviousData,
  });

  const canNext =
    step === 1
      ? draft.blockIds.length > 0
      : step === 2
        ? manual.activities.length - draft.excludedCodes.length + draft.customs.length > 0
        : step === 3
          ? problems.length === 0
          : true;

  if (result) {
    return (
      <Card className="flex flex-col gap-3">
        <h3 className="text-section-title font-semibold text-ap-ink">
          {draft.id ? t("plan.done.updated") : t("plan.done.applied")}
        </h3>
        <p className="text-sm text-ap-ink">
          {t("plan.done.body", {
            created: result.activities_created,
            blocks: result.allocation.blocks.length,
          })}
          {result.activities_kept > 0
            ? ` ${t("plan.done.kept", { count: result.activities_kept })}`
            : ""}
        </p>
        <div className="flex flex-wrap gap-2">
          <LinkButton to={`/board/${farmId}`}>{t("plan.done.viewBoard")}</LinkButton>
          <Button variant="secondary" onClick={onDone}>
            {t("plan.done.back")}
          </Button>
        </div>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <ol className="flex flex-wrap gap-2" aria-label={t("plan.steps.label")}>
        {([1, 2, 3, 4] as Step[]).map((n) => (
          <li
            key={n}
            aria-current={n === step ? "step" : undefined}
            className={clsx(
              "rounded-full px-3 py-1 text-xs font-semibold",
              n === step
                ? "bg-ap-primary text-white"
                : n < step
                  ? "bg-ap-primary-soft text-ap-primary"
                  : "bg-ap-line/70 text-ap-muted",
            )}
          >
            {n}. {t(`plan.steps.s${n}`)}
          </li>
        ))}
      </ol>

      {step === 1 ? (
        <BlocksStep
          draft={draft}
          onDraftChange={onDraftChange}
          matching={matching}
          allBlocks={(blocks.data?.items ?? []).map((b) => ({ id: b.id, code: b.code }))}
          blockLabel={blockLabel}
          loading={blocks.isLoading || appliable.isLoading}
        />
      ) : null}
      {step === 2 ? (
        <OperationsStep manual={manual} draft={draft} onDraftChange={onDraftChange} />
      ) : null}
      {step === 3 ? (
        <DatesStep
          manual={manual}
          draft={draft}
          onDraftChange={onDraftChange}
          blockLabel={blockLabel}
        />
      ) : null}
      {step === 4 ? (
        <div className="flex flex-col gap-3">
          {preview.isError ? (
            <StatusBanner kind="crit">
              {resolveErrorMessage(preview.error, t("plan.calendar.previewFailed"))}
            </StatusBanner>
          ) : null}
          {preview.data && preview.data.rejected_blocks.length > 0 ? (
            <StatusBanner kind="warn">{t("plan.calendar.rejected")}</StatusBanner>
          ) : null}
          {preview.data ? (
            <>
              <p className="text-sm text-ap-ink">
                {t("plan.calendar.summary", {
                  blocks: preview.data.blocks.length,
                  count: preview.data.total_activities,
                })}
              </p>
              <WeekCalendar
                blocks={preview.data.blocks}
                blockLabel={blockLabel}
                onMove={(blockId, key, date) =>
                  onDraftChange(setOverride(draft, blockId, key, date))
                }
              />
            </>
          ) : (
            <p className="text-sm text-ap-muted">{t("plan.calendar.loading")}</p>
          )}
          {save.isError ? (
            <StatusBanner kind="crit">
              {resolveErrorMessage(save.error, t("plan.calendar.saveFailed"))}
            </StatusBanner>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-ap-line pt-3">
        <Button variant="ghost" onClick={onDone}>
          {t("plan.cancel")}
        </Button>
        <div className="flex gap-2">
          {step > 1 ? (
            <Button variant="secondary" onClick={() => setStep((s) => (s - 1) as Step)}>
              {t("plan.back")}
            </Button>
          ) : null}
          {step < 4 ? (
            <Button disabled={!canNext} onClick={() => setStep((s) => (s + 1) as Step)}>
              {t("plan.next")}
            </Button>
          ) : (
            <Button
              disabled={save.isPending || !preview.data || preview.data.rejected_blocks.length > 0}
              onClick={() =>
                save.mutate(
                  { id: draft.id, body: request },
                  {
                    onSuccess: (r) => {
                      setResult(r);
                      flow.complete();
                      trackFeature("agri_operation", {
                        farm_id: farmId,
                        props: { action: "plan_saved", count: draft.blockIds.length },
                      });
                    },
                  },
                )
              }
            >
              {draft.id ? t("plan.saveChanges") : t("plan.apply")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- Step 1: blocks ------------------------------------------------------------

function BlocksStep({
  draft,
  onDraftChange,
  matching,
  allBlocks,
  blockLabel,
  loading,
}: {
  draft: PlanDraft;
  onDraftChange: (d: PlanDraft) => void;
  matching: {
    block_id: string;
    block_code: string | null;
    crop_path: string;
    planting_date: string | null;
  }[];
  allBlocks: { id: string; code: string }[];
  blockLabel: (id: string, fallback: string | null) => string;
  loading: boolean;
}): ReactNode {
  const { t } = useTranslation("agriOperation");
  const matchIds = new Set(matching.map((m) => m.block_id));
  const others = allBlocks.filter((b) => !matchIds.has(b.id));
  const toggle = (id: string): void => {
    const on = draft.blockIds.includes(id);
    onDraftChange({
      ...draft,
      blockIds: on ? draft.blockIds.filter((x) => x !== id) : [...draft.blockIds, id],
    });
  };
  const allOn = matching.length > 0 && matching.every((m) => draft.blockIds.includes(m.block_id));
  if (loading) return <p className="text-sm text-ap-muted">{t("plan.blocks.loading")}</p>;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-ap-ink">
          {t("plan.blocks.summary", { selected: draft.blockIds.length, total: matching.length })}
        </p>
        {matching.length > 0 ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              onDraftChange({ ...draft, blockIds: allOn ? [] : matching.map((m) => m.block_id) })
            }
          >
            {allOn ? t("plan.blocks.clearAll") : t("plan.blocks.selectAll")}
          </Button>
        ) : null}
      </div>
      {matching.length === 0 ? (
        <StatusBanner kind="warn">{t("plan.blocks.noneMatch")}</StatusBanner>
      ) : null}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {matching.map((m) => {
          const on = draft.blockIds.includes(m.block_id);
          return (
            <label
              key={m.block_id}
              className={clsx(
                "flex cursor-pointer items-start gap-2 rounded-card border p-3",
                on ? "border-ap-primary bg-ap-primary-soft" : "border-ap-line bg-ap-panel",
              )}
            >
              <input
                type="checkbox"
                className="mt-0.5"
                checked={on}
                onChange={() => toggle(m.block_id)}
              />
              <span className="min-w-0">
                <span className="block text-sm font-semibold text-ap-ink">
                  {blockLabel(m.block_id, m.block_code)}
                </span>
                <span className="block text-xs text-ap-muted">{m.crop_path}</span>
                {m.planting_date ? (
                  <span className="block text-xs text-ap-muted">
                    {t("plan.blocks.planted", { date: m.planting_date })}
                  </span>
                ) : null}
              </span>
            </label>
          );
        })}
      </div>
      {others.length > 0 ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-ap-muted">
            {t("plan.blocks.others", { count: others.length })}
          </summary>
          <ul className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
            {others.map((b) => (
              <li
                key={b.id}
                className="rounded-card border border-dashed border-ap-line px-3 py-2 text-ap-muted"
              >
                {blockLabel(b.id, b.code)} · {t("plan.blocks.otherReason")}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

// ---- Step 2: operations --------------------------------------------------------

function OperationsStep({
  manual,
  draft,
  onDraftChange,
}: {
  manual: OperationManual;
  draft: PlanDraft;
  onDraftChange: (d: PlanDraft) => void;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const layout = useMemo(
    () => seasonLayout(manual.varieties[0]?.stages ?? manual.stages, manual.is_perennial),
    [manual],
  );
  const [adding, setAdding] = useState(false);
  const included = manual.activities.length - draft.excludedCodes.length;
  const sorted = [...manual.activities].sort(
    (a, b) => (activityWeek(a, layout) ?? 999) - (activityWeek(b, layout) ?? 999),
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-ap-ink">
          {t("plan.ops.summary", {
            included,
            total: manual.activities.length,
            custom: draft.customs.length,
          })}
        </p>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => onDraftChange({ ...draft, excludedCodes: [], edits: {}, customs: [] })}
          >
            {t("plan.ops.reset")}
          </Button>
          <Button size="sm" onClick={() => setAdding(true)}>
            {t("plan.ops.add")}
          </Button>
        </div>
      </div>
      <p className="text-xs text-ap-muted">{t("plan.ops.hint")}</p>
      {adding ? (
        <CustomForm
          manual={manual}
          onCancel={() => setAdding(false)}
          onAdd={(c) => {
            onDraftChange({ ...draft, customs: [...draft.customs, c] });
            setAdding(false);
          }}
        />
      ) : null}
      <Card noPadding>
        <ul>
          {sorted.map((a) => {
            const excluded = draft.excludedCodes.includes(a.code);
            const edit = draft.edits[a.code] ?? {};
            const title =
              localizedField(lang, a.title ?? null, a.title_ar) ??
              t(`planTemplates:activityType.${a.activity_type}`);
            const week = activityWeek(a, layout);
            return (
              <li
                key={a.id}
                className={clsx(
                  "border-b border-ap-line last:border-b-0",
                  excluded && "opacity-50",
                )}
              >
                <details>
                  <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5">
                    <input
                      type="checkbox"
                      aria-label={t("plan.ops.include", { title })}
                      checked={!excluded}
                      onChange={() => onDraftChange(toggleCode(draft, a.code))}
                      onClick={(e) => e.stopPropagation()}
                    />
                    <span className="w-12 text-xs font-semibold tabular-nums text-ap-muted">
                      {week !== null ? t("manual.weekShort", { n: week }) : "—"}
                    </span>
                    <span
                      className={clsx(
                        "rounded px-2 py-0.5 text-meta font-semibold",
                        TYPE_CLASS[a.activity_type],
                      )}
                    >
                      {t(`planTemplates:activityType.${a.activity_type}`)}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-ap-ink">
                      {title}
                    </span>
                    {Object.keys(edit).length > 0 ? (
                      <span className="text-meta font-semibold text-ap-accent">
                        {t("plan.ops.edited")}
                      </span>
                    ) : null}
                  </summary>
                  <div className="grid gap-3 bg-ap-bg px-4 py-3 sm:grid-cols-3">
                    {(["product_name", "dosage", "notes"] as const).map((field) => (
                      <label
                        key={field}
                        className="flex flex-col gap-1 text-xs font-semibold text-ap-muted"
                      >
                        {t(`plan.ops.field.${field}`)}
                        <input
                          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm font-normal text-ap-ink"
                          value={edit[field] ?? a[field] ?? ""}
                          disabled={excluded}
                          onChange={(e) => {
                            const next = { ...edit, [field]: e.target.value };
                            if (e.target.value === (a[field] ?? "")) delete next[field];
                            const edits = { ...draft.edits, [a.code]: next };
                            if (Object.keys(next).length === 0) delete edits[a.code];
                            onDraftChange({ ...draft, edits });
                          }}
                        />
                      </label>
                    ))}
                  </div>
                </details>
              </li>
            );
          })}
          {draft.customs.map((c) => (
            <li key={c.key} className="flex items-center gap-3 border-t border-ap-line px-4 py-2.5">
              <span className="w-12 text-xs font-semibold text-ap-muted">
                {c.anchor === "week" ? t("manual.weekShort", { n: c.week ?? 1 }) : "—"}
              </span>
              <span
                className={clsx(
                  "rounded px-2 py-0.5 text-meta font-semibold",
                  TYPE_CLASS[c.activity_type],
                )}
              >
                {t(`planTemplates:activityType.${c.activity_type}`)}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm font-medium text-ap-ink">
                {c.title}
              </span>
              <span className="rounded bg-blue-50 px-1.5 py-0.5 text-meta font-semibold text-ap-accent">
                {t("plan.ops.custom")}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  onDraftChange({ ...draft, customs: draft.customs.filter((x) => x.key !== c.key) })
                }
              >
                {t("plan.ops.remove")}
              </Button>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function CustomForm({
  manual,
  onAdd,
  onCancel,
}: {
  manual: OperationManual;
  onAdd: (c: AllocationCustomActivity) => void;
  onCancel: () => void;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const [type, setType] = useState<PlanActivityType>("observation");
  const [title, setTitle] = useState("");
  const [anchor, setAnchor] = useState<"week" | "stage">("week");
  const [week, setWeek] = useState(1);
  const [stage, setStage] = useState(manual.stages[0]?.code ?? "");
  const [offset, setOffset] = useState(0);
  const [product, setProduct] = useState("");
  const [dosage, setDosage] = useState("");
  const [notes, setNotes] = useState("");
  const input =
    "rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm font-normal text-ap-ink";
  const label = "flex flex-col gap-1 text-xs font-semibold text-ap-muted";
  return (
    <Card
      as="form"
      className="grid gap-3 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (!title.trim()) return;
        onAdd({
          key: newCustomKey(),
          activity_type: type,
          title: title.trim(),
          anchor,
          week: anchor === "week" ? week : null,
          stage_code: anchor === "stage" ? stage : null,
          offset_days: anchor === "stage" ? offset : 0,
          duration_days: 1,
          product_name: product.trim() || null,
          dosage: dosage.trim() || null,
          notes: notes.trim() || null,
        });
      }}
    >
      <label className={label}>
        {t("plan.ops.field.type")}
        <select
          className={input}
          value={type}
          onChange={(e) => setType(e.target.value as PlanActivityType)}
        >
          {ACTIVITY_TYPES.map((x) => (
            <option key={x} value={x}>
              {t(`planTemplates:activityType.${x}`)}
            </option>
          ))}
        </select>
      </label>
      <label className={clsx(label, "sm:col-span-2")}>
        {t("plan.ops.field.title")}
        <input
          className={input}
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <label className={label}>
        {t("plan.ops.field.anchor")}
        <select
          className={input}
          value={anchor}
          onChange={(e) => setAnchor(e.target.value as "week" | "stage")}
        >
          <option value="week">{t("plan.ops.anchorWeek")}</option>
          <option value="stage">{t("plan.ops.anchorStage")}</option>
        </select>
      </label>
      {anchor === "week" ? (
        <label className={label}>
          {t("plan.ops.field.week")}
          <input
            className={input}
            type="number"
            min={1}
            max={104}
            value={week}
            onChange={(e) => setWeek(Math.max(1, Number(e.target.value) || 1))}
          />
        </label>
      ) : (
        <>
          <label className={label}>
            {t("plan.ops.field.stage")}
            <select className={input} value={stage} onChange={(e) => setStage(e.target.value)}>
              {manual.stages.map((s) => (
                <option key={s.code} value={s.code}>
                  {stageName(s, i18n.language)}
                </option>
              ))}
            </select>
          </label>
          <label className={label}>
            {t("plan.ops.field.offset")}
            <input
              className={input}
              type="number"
              value={offset}
              onChange={(e) => setOffset(Number(e.target.value) || 0)}
            />
          </label>
        </>
      )}
      <label className={label}>
        {t("plan.ops.field.product_name")}
        <input className={input} value={product} onChange={(e) => setProduct(e.target.value)} />
      </label>
      <label className={label}>
        {t("plan.ops.field.dosage")}
        <input className={input} value={dosage} onChange={(e) => setDosage(e.target.value)} />
      </label>
      <label className={clsx(label, "sm:col-span-3")}>
        {t("plan.ops.field.notes")}
        <input className={input} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" size="sm" disabled={!title.trim()}>
          {t("plan.ops.addConfirm")}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          {t("plan.cancel")}
        </Button>
      </div>
    </Card>
  );
}

// ---- Step 3: season and start dates ----------------------------------------------

function DatesStep({
  manual,
  draft,
  onDraftChange,
  blockLabel,
}: {
  manual: OperationManual;
  draft: PlanDraft;
  onDraftChange: (d: PlanDraft) => void;
  blockLabel: (id: string, fallback: string | null) => string;
}): ReactNode {
  const { t } = useTranslation("agriOperation");
  const input = "rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink";
  const label = "flex flex-col gap-1 text-xs font-semibold text-ap-muted";
  return (
    <div className="flex flex-col gap-4">
      <StatusBanner kind="info">
        {manual.is_perennial ? t("plan.dates.perennialNote") : t("plan.dates.annualNote")}
      </StatusBanner>
      <div className="flex flex-wrap gap-3">
        <label className={label}>
          {t("plan.dates.seasonLabel")}
          <input
            className={clsx(input, "min-w-56")}
            value={draft.seasonLabel}
            onChange={(e) => onDraftChange({ ...draft, seasonLabel: e.target.value })}
          />
        </label>
        <label className={label}>
          {t("plan.dates.seasonYear")}
          <input
            className={clsx(input, "w-28")}
            type="number"
            min={2000}
            max={2100}
            value={draft.seasonYear}
            onChange={(e) =>
              onDraftChange({ ...draft, seasonYear: Number(e.target.value) || draft.seasonYear })
            }
          />
        </label>
      </div>
      <fieldset className="flex flex-col gap-2">
        <legend className="text-xs font-semibold text-ap-muted">{t("plan.dates.mode")}</legend>
        {(["same", "per_block"] as const).map((mode) => (
          <div key={mode} className="flex flex-col">
            <label className="flex items-center gap-2 text-sm font-semibold text-ap-ink">
              <input
                type="radio"
                name="start-mode"
                checked={draft.startMode === mode}
                onChange={() => onDraftChange({ ...draft, startMode: mode })}
              />
              {t(`plan.dates.${mode}`)}
            </label>
            <span className="ms-6 text-xs text-ap-muted">{t(`plan.dates.${mode}Hint`)}</span>
          </div>
        ))}
      </fieldset>
      {draft.startMode === "same" ? (
        <label className={label}>
          {t("plan.dates.startDate")}
          <input
            className={clsx(input, "w-48")}
            type="date"
            value={draft.sameDate}
            onChange={(e) => onDraftChange({ ...draft, sameDate: e.target.value })}
          />
        </label>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {draft.blockIds.map((id) => (
            <Card
              key={id}
              noPadding
              className="flex items-center justify-between gap-2 px-3 py-2 text-sm text-ap-ink"
            >
              {blockLabel(id, null)}
              <input
                className={input}
                type="date"
                aria-label={t("plan.dates.startFor", { block: blockLabel(id, null) })}
                value={draft.perBlockDates[id] ?? ""}
                onChange={(e) =>
                  onDraftChange({
                    ...draft,
                    perBlockDates: { ...draft.perBlockDates, [id]: e.target.value },
                  })
                }
              />
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
