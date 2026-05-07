import clsx from "clsx";
import { useMemo, useState, type ReactNode } from "react";

import type { Block } from "@/api/blocks";
import type { ActivityType, Plan, PlanActivity } from "@/api/plans";
import { Modal } from "@/components/Modal";
import { useCreateActivity } from "@/queries/plans";
import { detectConflicts } from "@/rules/conflicts";
import { activityTypeBgClass, activityTypeLabel } from "@/rules/formatting";

interface Props {
  open: boolean;
  onClose: () => void;
  farmId: string;
  plan: Plan | null;
  blocks: Block[];
  existingActivities: PlanActivity[];
  /** Called after successful create with the new activity id list. */
  onCreated?: (created: PlanActivity[]) => void;
}

const TYPES: ReadonlyArray<{ value: ActivityType; description: string }> = [
  { value: "planting", description: "Establish or replant a crop." },
  { value: "fertilizing", description: "Apply nutrient blends or fertigation." },
  { value: "spraying", description: "Pesticide / fungicide application." },
  { value: "pruning", description: "Shaping, training, or sanitation cuts." },
  { value: "harvesting", description: "Pick fruit at maturity." },
  { value: "irrigation", description: "Manual irrigation event." },
];

export function NewActivityModal({
  open,
  onClose,
  farmId,
  plan,
  blocks,
  existingActivities,
  onCreated,
}: Props): ReactNode {
  const [step, setStep] = useState(0);
  const [type, setType] = useState<ActivityType | null>(null);
  const [selectedBlockIds, setSelectedBlockIds] = useState<string[]>([]);
  const [scheduledDate, setScheduledDate] = useState<string>(
    new Date(Date.now() + 2 * 86_400_000).toISOString().slice(0, 10),
  );
  const [startTime, setStartTime] = useState<string>("06:00");
  const [durationDays, setDurationDays] = useState<number>(1);
  const [productName, setProductName] = useState<string>("");
  const [dosage, setDosage] = useState<string>("");
  const [notes, setNotes] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCreateActivity();

  // Live conflict preview — synthesize candidate activities and re-run the
  // same detection used on the timeline.
  const previewConflicts = useMemo(() => {
    if (!type || selectedBlockIds.length === 0) return [];
    const candidates: PlanActivity[] = selectedBlockIds.map((bid, i) => ({
      id: `__candidate-${i}`,
      plan_id: plan?.id ?? "preview",
      block_id: bid,
      activity_type: type,
      scheduled_date: scheduledDate,
      duration_days: durationDays,
      start_time: startTime,
      product_name: productName || null,
      dosage: dosage || null,
      notes: notes || null,
      status: "scheduled",
      completed_at: null,
      completed_by: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }));
    return detectConflicts([...existingActivities, ...candidates]).filter((c) =>
      c.activityIds.some((id) => id.startsWith("__candidate-")),
    );
  }, [type, selectedBlockIds, scheduledDate, durationDays, startTime, productName, dosage, notes, existingActivities, plan?.id]);

  const reset = (): void => {
    setStep(0);
    setType(null);
    setSelectedBlockIds([]);
    setProductName("");
    setDosage("");
    setNotes("");
    setError(null);
  };

  const handleClose = (): void => {
    reset();
    onClose();
  };

  const handleNext = (): void => {
    if (step === 0 && !type) return;
    if (step === 1 && selectedBlockIds.length === 0) return;
    setStep((s) => Math.min(s + 1, 3));
  };

  const handleBack = (): void => setStep((s) => Math.max(s - 1, 0));

  const handleSubmit = async (): Promise<void> => {
    if (!plan || !type) return;
    setSubmitting(true);
    setError(null);
    const created: PlanActivity[] = [];
    try {
      for (const bid of selectedBlockIds) {
        const out = await create.mutateAsync({
          planId: plan.id,
          payload: {
            block_id: bid,
            activity_type: type,
            scheduled_date: scheduledDate,
            duration_days: durationDays,
            start_time: startTime || null,
            product_name: productName || null,
            dosage: dosage || null,
            notes: notes || null,
          },
        });
        created.push(out);
      }
      onCreated?.(created);
      handleClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  if (!plan) {
    return (
      <Modal open={open} onClose={handleClose} labelledBy="new-activity-title">
        <h2 id="new-activity-title" className="text-lg font-semibold text-ap-ink">
          New activity
        </h2>
        <p className="mt-3 text-sm text-ap-muted">
          Create a vegetation plan for this farm before scheduling activities.
        </p>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-md border border-ap-line px-3 py-1.5 text-sm font-medium"
          >
            Close
          </button>
        </div>
      </Modal>
    );
  }

  return (
    <Modal open={open} onClose={handleClose} labelledBy="new-activity-title">
      <h2 id="new-activity-title" className="text-lg font-semibold text-ap-ink">
        New activity
      </h2>
      <Stepper step={step} />
      <div className="mt-4 min-h-[280px]">
        {step === 0 ? (
          <Step1Type type={type} onPick={setType} />
        ) : step === 1 ? (
          <Step2Lanes
            blocks={blocks}
            selected={selectedBlockIds}
            onToggle={(id) =>
              setSelectedBlockIds((prev) =>
                prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
              )
            }
          />
        ) : step === 2 ? (
          <Step3Schedule
            date={scheduledDate}
            onDate={setScheduledDate}
            startTime={startTime}
            onStartTime={setStartTime}
            durationDays={durationDays}
            onDuration={setDurationDays}
            previewConflicts={previewConflicts}
          />
        ) : (
          <Step4Details
            farmId={farmId}
            type={type!}
            blocks={blocks.filter((b) => selectedBlockIds.includes(b.id))}
            scheduledDate={scheduledDate}
            startTime={startTime}
            durationDays={durationDays}
            productName={productName}
            onProduct={setProductName}
            dosage={dosage}
            onDosage={setDosage}
            notes={notes}
            onNotes={setNotes}
            previewConflicts={previewConflicts}
          />
        )}
      </div>
      {error ? (
        <p role="alert" className="mt-3 rounded-md bg-ap-crit-soft p-2 text-sm text-ap-crit">
          {error}
        </p>
      ) : null}
      <div className="mt-4 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={handleClose}
          className="text-sm text-ap-muted hover:underline"
        >
          Cancel
        </button>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={step === 0}
            onClick={handleBack}
            className="rounded-md border border-ap-line px-3 py-1.5 text-sm font-medium disabled:opacity-40"
          >
            Back
          </button>
          {step < 3 ? (
            <button
              type="button"
              onClick={handleNext}
              disabled={
                (step === 0 && !type) || (step === 1 && selectedBlockIds.length === 0)
              }
              className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Next
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={submitting}
              className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              {submitting ? "Creating…" : "Create activity"}
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}

function Stepper({ step }: { step: number }): ReactNode {
  const labels = ["Type", "Land units", "Schedule", "Details"];
  return (
    <ol className="mt-3 flex items-center gap-2 text-xs">
      {labels.map((label, i) => (
        <li key={label} className="flex items-center gap-2">
          <span
            className={clsx(
              "flex h-6 w-6 items-center justify-center rounded-full",
              i < step
                ? "bg-ap-primary text-white"
                : i === step
                  ? "bg-ap-ink text-white"
                  : "bg-ap-line text-ap-muted",
            )}
          >
            {i + 1}
          </span>
          <span className={clsx(i === step ? "font-medium text-ap-ink" : "text-ap-muted")}>
            {label}
          </span>
          {i < labels.length - 1 ? (
            <span aria-hidden="true" className="h-px w-6 bg-ap-line" />
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function Step1Type({
  type,
  onPick,
}: {
  type: ActivityType | null;
  onPick: (t: ActivityType) => void;
}): ReactNode {
  return (
    <div>
      <p className="mb-3 text-sm text-ap-muted">Pick the type of activity to schedule.</p>
      <div className="grid grid-cols-2 gap-2">
        {TYPES.map((t) => {
          const selected = type === t.value;
          return (
            <button
              type="button"
              key={t.value}
              onClick={() => onPick(t.value)}
              className={clsx(
                "flex flex-col items-start rounded-lg border p-3 text-start transition-colors",
                selected
                  ? "border-ap-primary bg-ap-primary-soft"
                  : "border-ap-line hover:bg-ap-line/30",
              )}
            >
              <span
                aria-hidden="true"
                className={clsx("mb-2 h-2 w-8 rounded-full", activityTypeBgClass(t.value))}
              />
              <span className="text-sm font-medium text-ap-ink">{activityTypeLabel(t.value)}</span>
              <span className="text-xs text-ap-muted">{t.description}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Step2Lanes({
  blocks,
  selected,
  onToggle,
}: {
  blocks: Block[];
  selected: string[];
  onToggle: (id: string) => void;
}): ReactNode {
  return (
    <div>
      <p className="mb-3 text-sm text-ap-muted">Pick one or more land units.</p>
      <div className="flex flex-wrap gap-2">
        {blocks.map((b) => {
          const isSelected = selected.includes(b.id);
          return (
            <button
              type="button"
              key={b.id}
              onClick={() => onToggle(b.id)}
              className={clsx(
                "rounded-full border px-3 py-1.5 text-sm",
                isSelected
                  ? "border-ap-primary bg-ap-primary-soft text-ap-primary"
                  : "border-ap-line hover:bg-ap-line/30",
              )}
            >
              {b.name ?? b.code}
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface Step3Props {
  date: string;
  onDate: (v: string) => void;
  startTime: string;
  onStartTime: (v: string) => void;
  durationDays: number;
  onDuration: (v: number) => void;
  previewConflicts: ReadonlyArray<unknown>;
}

function Step3Schedule({
  date,
  onDate,
  startTime,
  onStartTime,
  durationDays,
  onDuration,
  previewConflicts,
}: Step3Props): ReactNode {
  return (
    <div>
      <div className="grid grid-cols-2 gap-3">
        <label className="block text-sm">
          <span className="block text-xs font-medium uppercase tracking-wider text-ap-muted">
            Date
          </span>
          <input
            type="date"
            value={date}
            onChange={(e) => onDate(e.target.value)}
            className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="block text-xs font-medium uppercase tracking-wider text-ap-muted">
            Start time
          </span>
          <input
            type="time"
            value={startTime}
            onChange={(e) => onStartTime(e.target.value)}
            className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="block text-xs font-medium uppercase tracking-wider text-ap-muted">
            Duration (days)
          </span>
          <input
            type="number"
            min={1}
            max={60}
            value={durationDays}
            onChange={(e) => onDuration(Number(e.target.value))}
            className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-2 py-1.5"
          />
        </label>
      </div>
      <div
        className={clsx(
          "mt-3 rounded-md p-3 text-sm",
          previewConflicts.length === 0
            ? "bg-ap-primary-soft text-ap-primary"
            : "bg-ap-warn-soft text-ap-warn",
        )}
        aria-live="polite"
      >
        {previewConflicts.length === 0
          ? "✓ No scheduling conflicts detected for the selected window."
          : `⚠ ${previewConflicts.length} conflict${previewConflicts.length === 1 ? "" : "s"} detected — see review step.`}
      </div>
    </div>
  );
}

interface Step4Props {
  farmId: string;
  type: ActivityType;
  blocks: Block[];
  scheduledDate: string;
  startTime: string;
  durationDays: number;
  productName: string;
  onProduct: (v: string) => void;
  dosage: string;
  onDosage: (v: string) => void;
  notes: string;
  onNotes: (v: string) => void;
  previewConflicts: ReadonlyArray<{ message: string }>;
}

function Step4Details({
  type,
  blocks,
  scheduledDate,
  startTime,
  durationDays,
  productName,
  onProduct,
  dosage,
  onDosage,
  notes,
  onNotes,
  previewConflicts,
}: Step4Props): ReactNode {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <label className="block text-sm">
          <span className="block text-xs font-medium uppercase tracking-wider text-ap-muted">
            Product
          </span>
          <input
            type="text"
            value={productName}
            onChange={(e) => onProduct(e.target.value)}
            className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-2 py-1.5"
          />
        </label>
        <label className="block text-sm">
          <span className="block text-xs font-medium uppercase tracking-wider text-ap-muted">
            Dosage
          </span>
          <input
            type="text"
            value={dosage}
            onChange={(e) => onDosage(e.target.value)}
            className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-2 py-1.5"
          />
        </label>
      </div>
      <label className="block text-sm">
        <span className="block text-xs font-medium uppercase tracking-wider text-ap-muted">
          Notes
        </span>
        <textarea
          value={notes}
          onChange={(e) => onNotes(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded-md border border-ap-line bg-ap-panel px-2 py-1.5"
        />
      </label>
      <div className="rounded-md border border-ap-line bg-ap-bg p-3 text-sm">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ap-muted">
          Summary
        </h3>
        <ul className="mt-1 list-inside list-disc text-ap-ink">
          <li>{activityTypeLabel(type)} on {blocks.length} land unit{blocks.length === 1 ? "" : "s"}</li>
          <li>
            {scheduledDate}
            {startTime ? ` at ${startTime}` : ""} for {durationDays} day{durationDays === 1 ? "" : "s"}
          </li>
          {productName ? <li>Product: {productName}</li> : null}
          {dosage ? <li>Dosage: {dosage}</li> : null}
        </ul>
      </div>
      {previewConflicts.length > 0 ? (
        <div className="rounded-md bg-ap-warn-soft p-3 text-sm text-ap-warn">
          {previewConflicts.map((c, i) => (
            <p key={i}>⚠ {c.message}</p>
          ))}
        </div>
      ) : null}
    </div>
  );
}
