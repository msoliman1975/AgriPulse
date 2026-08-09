import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  applyBulkCropAssignment,
  listBulkCropCandidates,
  previewBulkCropAssignment,
  type BulkConflictMode,
  type BulkCropApplyResult,
  type BulkCropAssignmentPayload,
  type BulkCropPreview,
} from "@/api/bulkCropAssignment";
import { resolveCropAttributes } from "@/api/crops";
import { isApiError } from "@/api/errors";
import { listFarms } from "@/api/farms";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { KPICard } from "@/components/KPICard";
import { KPIRow } from "@/components/KPIRow";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { queryState } from "@/components/asyncState";
import { CropPicker } from "@/modules/farms/components/CropPicker";
import { AttributeInput } from "@/modules/farms/components/CropAttributesCard";
import {
  buildPayload,
  isRequired as attributeRequired,
  label as attributeLabel,
  missingRequired,
  visibleDefinitions,
  type AttributeValues,
} from "@/modules/farms/lib/cropAttributeForm";
import { BulkBlockPicker, type BlockOverride } from "@/modules/settings/components/BulkBlockPicker";
import { BulkCropOutcomeTable } from "@/modules/settings/components/BulkCropOutcomeTable";
import { useCapability } from "@/rbac/useCapability";

const INPUT =
  "w-full rounded-md border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm " +
  "focus:outline-none focus:ring-1 focus:ring-ap-primary";

type StepId = 1 | 2 | 3 | 4;

/** Data types this hub can bulk-edit. Only the live one is selectable; the
 *  rest are listed so the page reads as a hub with one type built rather than
 *  a crop screen that will need renaming when the second arrives. */
const DATA_TYPES = [
  { id: "crop", live: true },
  { id: "irrigation", live: false },
  { id: "grid", live: false },
  { id: "subscriptions", live: false },
] as const;

/**
 * /settings/bulk — change one setting across many blocks of one farm.
 *
 * Four steps: scope, values, blocks, preview. The preview is not decoration —
 * it posts the exact payload the apply will post, to an endpoint that computes
 * outcomes without writing, so what the table shows is what the run does.
 */
export function BulkUpdatesPage(): ReactNode {
  const { t, i18n } = useTranslation("bulkUpdates");
  const lang = i18n.language;
  const queryClient = useQueryClient();
  const canBulk = useCapability("crop_assignment.create");

  const [step, setStep] = useState<StepId>(1);
  const [farmId, setFarmId] = useState<string | null>(null);
  const [dataType, setDataType] = useState<string>("crop");

  // ---- step 2: the shared values -----------------------------------------
  const [cropId, setCropId] = useState<string | null>(null);
  const [varietyId, setVarietyId] = useState<string | null>(null);
  const [strainId, setStrainId] = useState<string | null>(null);
  const [depthComplete, setDepthComplete] = useState(false);
  const [cropPath, setCropPath] = useState<string | null>(null);
  const [attrValues, setAttrValues] = useState<AttributeValues>({});
  const [season, setSeason] = useState("");
  const [planting, setPlanting] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [notes, setNotes] = useState("");
  const [conflictMode, setConflictMode] = useState<BulkConflictMode>("skip");

  // ---- step 3 ------------------------------------------------------------
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [overrides, setOverrides] = useState<Record<string, BlockOverride>>({});

  // ---- step 4 ------------------------------------------------------------
  const [preview, setPreview] = useState<BulkCropPreview | null>(null);
  const [result, setResult] = useState<BulkCropApplyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const farmsQuery = useQuery({ queryKey: ["farms", "bulk"], queryFn: () => listFarms({}) });
  const farms = useMemo(() => farmsQuery.data?.items ?? [], [farmsQuery.data]);

  const candidatesQuery = useQuery({
    queryKey: ["bulk_crop_candidates", farmId] as const,
    queryFn: () => listBulkCropCandidates(farmId as string),
    enabled: farmId !== null,
  });
  const candidates = useMemo(() => candidatesQuery.data ?? [], [candidatesQuery.data]);

  const attrQuery = useQuery({
    queryKey: ["crop_attributes", "resolved", cropPath] as const,
    queryFn: () => resolveCropAttributes(cropPath as string),
    enabled: cropPath !== null,
    staleTime: 60_000,
  });
  const attrDefs = useMemo(() => attrQuery.data?.definitions ?? [], [attrQuery.data]);
  const attrVisible = useMemo(
    () => visibleDefinitions(attrDefs, attrValues),
    [attrDefs, attrValues],
  );
  const attrMissing = useMemo(() => missingRequired(attrDefs, attrValues), [attrDefs, attrValues]);

  // Definitions differ per crop, so values entered for a previous crop are
  // codes this one has never heard of. Only clear on a real change — clearing
  // on an unchanged path would discard what the user is mid-way through typing.
  const handleCropPathChange = useCallback((path: string | null) => {
    setCropPath((prev) => {
      if (prev !== path) setAttrValues({});
      return path;
    });
  }, []);

  const payload = useMemo((): BulkCropAssignmentPayload | null => {
    if (!cropId || !season) return null;
    return {
      conflict_mode: conflictMode,
      targets: [...selected].map((blockId) => ({
        block_id: blockId,
        season_label: overrides[blockId]?.season_label ?? null,
        planting_date: overrides[blockId]?.planting_date ?? null,
      })),
      crop_id: cropId,
      crop_variety_id: varietyId,
      crop_variety_strain_id: strainId,
      season_label: season,
      effective_from: effectiveFrom || null,
      planting_date: planting || null,
      notes: notes || null,
      attributes: buildPayload(attrDefs, attrValues),
    };
  }, [
    conflictMode,
    selected,
    overrides,
    cropId,
    varietyId,
    strainId,
    season,
    effectiveFrom,
    planting,
    notes,
    attrDefs,
    attrValues,
  ]);

  const previewMutation = useMutation({
    mutationFn: () =>
      previewBulkCropAssignment(farmId as string, payload as BulkCropAssignmentPayload),
    onSuccess: (data) => {
      setPreview(data);
      setError(null);
    },
    onError: (err: unknown) =>
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : t("errors.preview")),
  });

  const applyMutation = useMutation({
    mutationFn: () =>
      applyBulkCropAssignment(farmId as string, payload as BulkCropAssignmentPayload),
    onSuccess: (data) => {
      setResult(data);
      setError(null);
      // The picker's "current crop" column is now stale for every block the
      // run touched.
      void queryClient.invalidateQueries({ queryKey: ["bulk_crop_candidates", farmId] });
    },
    onError: (err: unknown) =>
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : t("errors.apply")),
  });

  const blockingReason = ((): string | null => {
    if (step === 1) return farmId ? null : t("validation.pickFarm");
    if (step === 2) {
      if (!cropId || !depthComplete) return t("validation.pickCrop");
      if (!season.trim()) return t("validation.season");
      if (attrMissing.length > 0) return t("validation.cropField");
      return null;
    }
    if (step === 3) return selected.size > 0 ? null : t("validation.pickBlocks");
    return null;
  })();

  const goTo = (next: StepId): void => {
    if (next > step && blockingReason) return;
    // Any change of selection or values invalidates a preview that was
    // computed from the old ones — showing it against a new payload is
    // exactly the lie the preview exists to prevent.
    if (next !== 4) {
      setPreview(null);
      setResult(null);
    }
    setStep(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const resetRun = (): void => {
    setPreview(null);
    setResult(null);
    setSelected(new Set());
    setOverrides({});
    setStep(1);
  };

  if (!canBulk) {
    return (
      <div className="py-12 text-center">
        <h2 className="text-section-title text-ap-ink">{t("denied.title")}</h2>
        <p className="mt-2 text-sm text-ap-muted">{t("denied.body")}</p>
      </div>
    );
  }

  const steps: { id: StepId; label: string; sub: string }[] = [
    {
      id: 1,
      label: t("steps.scope"),
      sub: farms.find((f) => f.id === farmId)?.name ?? t("steps.scopeSub"),
    },
    { id: 2, label: t("steps.details"), sub: cropPath ?? t("steps.detailsSub") },
    {
      id: 3,
      label: t("steps.blocks"),
      sub: selected.size ? t("steps.blocksCount", { count: selected.size }) : t("steps.blocksSub"),
    },
    {
      id: 4,
      label: t("steps.review"),
      sub: result ? t("steps.reviewDone") : t("steps.reviewSub"),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />

      <nav aria-label={t("steps.label")} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {steps.map((s) => {
          const state = s.id === step ? "active" : s.id < step ? "done" : "todo";
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => goTo(s.id)}
              aria-current={state === "active" ? "step" : undefined}
              className={`flex items-center gap-2 rounded-card border px-3 py-2 text-start ${
                state === "active"
                  ? "border-ap-primary bg-ap-primary-soft/40"
                  : "border-ap-line bg-ap-panel"
              }`}
            >
              <span
                className={`grid h-6 w-6 flex-none place-items-center rounded-full text-xs font-semibold ${
                  state === "active"
                    ? "bg-ap-primary text-white"
                    : state === "done"
                      ? "bg-ap-primary-soft text-ap-primary"
                      : "bg-ap-line/70 text-ap-muted"
                }`}
              >
                {s.id}
              </span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-ap-ink">{s.label}</span>
                <span className="block truncate text-xs text-ap-muted">{s.sub}</span>
              </span>
            </button>
          );
        })}
      </nav>

      {error ? <StatusBanner kind="crit">{error}</StatusBanner> : null}

      {/* ================= step 1 — scope ================= */}
      {step === 1 ? (
        <>
          <Card title={t("scope.farmTitle")}>
            <AsyncBoundary
              state={queryState(farmsQuery)}
              empty={<EmptyState message={t("scope.noFarms")} />}
              isEmpty={(page) => page.items.length === 0}
            >
              {() => (
                <Field label={t("scope.farmLabel")} required>
                  {(a11y) => (
                    <select
                      {...a11y}
                      className={INPUT}
                      value={farmId ?? ""}
                      onChange={(e) => {
                        setFarmId(e.target.value || null);
                        setSelected(new Set());
                        setOverrides({});
                      }}
                    >
                      <option value="">{t("scope.farmPlaceholder")}</option>
                      {farms.map((f) => (
                        <option key={f.id} value={f.id}>
                          {f.name}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
              )}
            </AsyncBoundary>
          </Card>

          <Card title={t("scope.typeTitle")}>
            <div className="grid gap-2 sm:grid-cols-2">
              {DATA_TYPES.map((type) => (
                <label
                  key={type.id}
                  htmlFor={`bulk-type-${type.id}`}
                  className={`grid grid-cols-[auto_1fr] items-start gap-x-2.5 gap-y-0.5 rounded-card border p-3 ${
                    type.live
                      ? `cursor-pointer ${
                          dataType === type.id
                            ? "border-ap-primary bg-ap-primary-soft/40"
                            : "border-ap-line hover:border-ap-primary"
                        }`
                      : "cursor-not-allowed border-ap-line opacity-60"
                  }`}
                >
                  <input
                    id={`bulk-type-${type.id}`}
                    type="radio"
                    name="dataType"
                    className="mt-1 row-span-2"
                    value={type.id}
                    checked={dataType === type.id}
                    disabled={!type.live}
                    onChange={() => setDataType(type.id)}
                  />
                  <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-ap-ink">
                    {t(`scope.types.${type.id}.name`)}
                    <Pill kind={type.live ? "ok" : "neutral"}>
                      {type.live ? t("scope.available") : t("scope.planned")}
                    </Pill>
                  </span>
                  <span className="col-start-2 text-xs text-ap-muted">
                    {t(`scope.types.${type.id}.desc`)}
                  </span>
                </label>
              ))}
            </div>
          </Card>
        </>
      ) : null}

      {/* ================= step 2 — values ================= */}
      {step === 2 ? (
        <>
          <Card title={t("details.cropTitle")}>
            <CropPicker
              cropId={cropId}
              cropVarietyId={varietyId}
              cropVarietyStrainId={strainId}
              onChange={(c, v, s) => {
                setCropId(c);
                setVarietyId(v);
                setStrainId(s);
              }}
              onValidityChange={setDepthComplete}
              onCropPathChange={handleCropPathChange}
            />
          </Card>

          <Card title={t("details.seasonTitle")}>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label={t("details.season")} required>
                {(a11y) => (
                  <input
                    {...a11y}
                    className={INPUT}
                    value={season}
                    placeholder="2026A"
                    onChange={(e) => setSeason(e.target.value)}
                  />
                )}
              </Field>
              <Field label={t("details.planting")}>
                {(a11y) => (
                  <input
                    {...a11y}
                    type="date"
                    className={INPUT}
                    value={planting}
                    onChange={(e) => setPlanting(e.target.value)}
                  />
                )}
              </Field>
              <Field label={t("details.effectiveFrom")} help={t("details.effectiveFromHelp")}>
                {(a11y) => (
                  <input
                    {...a11y}
                    type="date"
                    className={INPUT}
                    value={effectiveFrom}
                    onChange={(e) => setEffectiveFrom(e.target.value)}
                  />
                )}
              </Field>
            </div>
          </Card>

          {/* Crop fields for the chosen crop. Written with the assignment in
              one transaction, so a bulk run produces complete assignments
              rather than N blocks needing a follow-up visit each. */}
          {cropPath ? (
            <Card title={t("details.cropFieldsTitle")}>
              {attrVisible.length === 0 ? (
                <p className="text-sm text-ap-muted">{t("details.noCropFields")}</p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {attrVisible.map((def) => {
                    const unit = lang.startsWith("ar") ? def.unit_ar : def.unit_en;
                    return (
                      <Field
                        key={def.code}
                        label={
                          <span>
                            {attributeLabel(def, lang)}
                            {unit ? <span className="ms-1 text-ap-muted">({unit})</span> : null}
                          </span>
                        }
                        required={attributeRequired(def, attrValues)}
                        error={
                          attrMissing.includes(def.code) ? t("validation.fieldRequired") : undefined
                        }
                      >
                        {(a11y) => (
                          <AttributeInput
                            def={def}
                            value={attrValues[def.code]}
                            readOnly={false}
                            lang={lang}
                            a11y={a11y}
                            onChange={(v) => setAttrValues((prev) => ({ ...prev, [def.code]: v }))}
                          />
                        )}
                      </Field>
                    );
                  })}
                </div>
              )}
            </Card>
          ) : null}

          <Card title={t("details.notesTitle")}>
            <textarea
              className={`${INPUT} min-h-[70px]`}
              aria-label={t("details.notesTitle")}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </Card>

          <Card title={t("conflict.title")}>
            <div className="grid gap-2 sm:grid-cols-2">
              {(["skip", "replace"] as const).map((mode) => (
                <label
                  key={mode}
                  htmlFor={`bulk-conflict-${mode}`}
                  className={`grid cursor-pointer grid-cols-[auto_1fr] items-start gap-x-2.5 gap-y-0.5 rounded-card border p-3 ${
                    conflictMode === mode
                      ? "border-ap-primary bg-ap-primary-soft/40"
                      : "border-ap-line hover:border-ap-primary"
                  }`}
                >
                  <input
                    id={`bulk-conflict-${mode}`}
                    type="radio"
                    name="conflictMode"
                    className="row-span-2 mt-1"
                    value={mode}
                    checked={conflictMode === mode}
                    onChange={() => setConflictMode(mode)}
                  />
                  <span className="text-sm font-medium text-ap-ink">
                    {t(`conflict.${mode}.name`)}
                  </span>
                  <span className="col-start-2 text-xs text-ap-muted">
                    {t(`conflict.${mode}.desc`)}
                  </span>
                </label>
              ))}
            </div>
            <p className="mt-3 text-xs text-ap-muted">{t("conflict.historyNote")}</p>
          </Card>
        </>
      ) : null}

      {/* ================= step 3 — blocks ================= */}
      {step === 3 ? (
        <AsyncBoundary
          state={queryState(candidatesQuery)}
          empty={<EmptyState message={t("blocks.none")} />}
        >
          {(rows) => (
            <BulkBlockPicker
              candidates={rows}
              selected={selected}
              onSelectedChange={setSelected}
              overrides={overrides}
              onOverridesChange={setOverrides}
              sharedSeason={season}
              conflictMode={conflictMode}
            />
          )}
        </AsyncBoundary>
      ) : null}

      {/* ================= step 4 — preview & apply ================= */}
      {step === 4 ? (
        <>
          {result === null && preview === null ? (
            <Card title={t("review.title")}>
              <p className="text-sm text-ap-muted">
                {t("review.blurb", {
                  count: selected.size,
                  assigned: candidates.filter((c) => selected.has(c.block_id) && c.current).length,
                })}
              </p>
              <div className="mt-3">
                <Button
                  onClick={() => previewMutation.mutate()}
                  disabled={previewMutation.isPending || payload === null}
                >
                  {previewMutation.isPending ? t("review.running") : t("review.run")}
                </Button>
              </div>
            </Card>
          ) : null}

          {result === null && preview !== null ? (
            <>
              <KPIRow>
                <KPICard title={t("review.kpi.selected")} value={preview.items.length} />
                <KPICard title={t("review.kpi.assign")} value={preview.assign_count} />
                <KPICard title={t("review.kpi.replace")} value={preview.replace_count} />
                <KPICard title={t("review.kpi.skip")} value={preview.skip_count} />
              </KPIRow>
              <BulkCropOutcomeTable items={preview.items} />
              <Card>
                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    onClick={() => applyMutation.mutate()}
                    disabled={
                      applyMutation.isPending || preview.assign_count + preview.replace_count === 0
                    }
                  >
                    {applyMutation.isPending
                      ? t("review.applying")
                      : t("review.apply", {
                          count: preview.assign_count + preview.replace_count,
                        })}
                  </Button>
                  <Button variant="ghost" onClick={() => goTo(3)}>
                    {t("review.changeSelection")}
                  </Button>
                  <span className="text-sm text-ap-muted">
                    {preview.replace_count > 0
                      ? t("review.replaceWarning", { count: preview.replace_count })
                      : t("review.noReplace")}
                  </span>
                </div>
              </Card>
            </>
          ) : null}

          {result !== null ? (
            <>
              <StatusBanner kind={result.failed_count > 0 ? "warn" : "info"}>
                {t("result.summary", {
                  applied: result.applied_count,
                  failed: result.failed_count,
                  skipped: result.skipped_count,
                })}
              </StatusBanner>
              <BulkCropOutcomeTable items={result.items} />
              <Card>
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="secondary" onClick={resetRun}>
                    {t("result.startAnother")}
                  </Button>
                  <span className="text-sm text-ap-muted">{t("result.auditNote")}</span>
                </div>
              </Card>
            </>
          ) : null}
        </>
      ) : null}

      {/* ================= wizard footer ================= */}
      {step !== 4 || (preview === null && result === null) ? (
        <div className="flex flex-wrap items-center gap-3 border-t border-ap-line pt-3">
          <Button variant="ghost" disabled={step === 1} onClick={() => goTo((step - 1) as StepId)}>
            {t("nav.back")}
          </Button>
          {step < 4 ? (
            <Button disabled={blockingReason !== null} onClick={() => goTo((step + 1) as StepId)}>
              {step === 3 ? t("nav.toReview") : t("nav.continue")}
            </Button>
          ) : null}
          {blockingReason ? <span className="text-sm text-ap-muted">{blockingReason}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
