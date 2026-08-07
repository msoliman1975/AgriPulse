import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { assignBlockCrop, listBlockCrops } from "@/api/cropAssignments";
import { resolveCropAttributes } from "@/api/crops";
import { isApiError } from "@/api/errors";
import { Button } from "@/components/Button";
import { Field } from "@/components/Field";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { CropPicker } from "@/modules/farms/components/CropPicker";
import { AttributeInput, CropAttributesCard } from "@/modules/farms/components/CropAttributesCard";
import {
  buildPayload,
  isRequired as attributeRequired,
  label as attributeLabel,
  missingRequired,
  visibleDefinitions,
  type AttributeValues,
} from "@/modules/farms/lib/cropAttributeForm";
import {
  currentAssignment,
  findConflict,
  gaps,
  humanDuration,
  openAssignmentToClose,
  stateOn,
  todayIso,
  type ValidityState,
} from "@/modules/farms/lib/assignmentValidity";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  blockId: string;
  farmId: string;
  /** Refetch the block detail after a successful assignment. */
  onAssigned: () => void;
}

const INPUT =
  "block w-full rounded-md border border-ap-line bg-white px-2 py-1 text-xs text-ap-ink";

const STATE_PILL: Record<ValidityState, string> = {
  current: "bg-ap-primary-soft text-[#24501f] border-[#c3ddc1]",
  past: "bg-[#f1f0ea] text-[#55594f] border-[#e0ddd2]",
  scheduled: "bg-[#e2eef5] text-[#155273] border-[#c3dced]",
};

/**
 * Crop → block assignment with validity dates.
 *
 * Three things on one panel, because they are one decision:
 *   1. what is on this block now, with its dates and its crop fields;
 *   2. optionally, everything that came before, with from → until;
 *   3. the form to assign the next crop — which says, before you commit,
 *      which assignment it will close.
 *
 * "Current" is the assignment whose validity range contains today, never the
 * stored `is_current` flag: that flag only moves when someone assigns a crop,
 * so a finished season used to keep reading as the block's crop for months.
 */
export function CropAssignmentPanel({ blockId, farmId, onAssigned }: Props): ReactNode {
  const { t, i18n } = useTranslation("farms");
  const lang = i18n.language;
  const canAssign = useCapability("crop_assignment.create", { farmId });
  const queryClient = useQueryClient();
  const today = todayIso();

  const query = useQuery({
    queryKey: ["block_crops", blockId] as const,
    queryFn: () => listBlockCrops(blockId),
  });

  const [showHistory, setShowHistory] = useState(false);
  const [cropId, setCropId] = useState<string | null>(null);
  const [varietyId, setVarietyId] = useState<string | null>(null);
  const [strainId, setStrainId] = useState<string | null>(null);
  const [depthComplete, setDepthComplete] = useState(false);
  const [season, setSeason] = useState("");
  const [from, setFrom] = useState(today);
  const [to, setTo] = useState("");
  const [planting, setPlanting] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Crop fields for the assignment being created. Resolved from the chosen
  // crop path *before* the assignment exists, which is what makes this one
  // screen instead of assign-then-come-back-and-fill-in.
  const [cropPath, setCropPath] = useState<string | null>(null);
  const [attrValues, setAttrValues] = useState<AttributeValues>({});

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

  const rows = useMemo(
    () => [...(query.data ?? [])].sort((a, b) => (a.effective_from < b.effective_from ? 1 : -1)),
    [query.data],
  );
  const current = useMemo(() => currentAssignment(rows, today), [rows, today]);
  const closing = useMemo(() => (from ? openAssignmentToClose(rows, from) : null), [rows, from]);
  const conflict = useMemo(
    () => (from ? findConflict(rows, from, to || null, closing?.id ?? null) : null),
    [rows, from, to, closing],
  );
  const fallow = useMemo(() => gaps(rows), [rows]);

  const invertedRange = Boolean(to && from && to <= from);
  const canSubmit =
    canAssign &&
    Boolean(cropId) &&
    depthComplete &&
    Boolean(season) &&
    Boolean(from) &&
    !conflict &&
    !invertedRange &&
    // A required crop field blocks the save here rather than after it: the
    // server writes the assignment and its fields in one transaction and
    // would reject the whole thing.
    attrMissing.length === 0;

  const assign = useMutation({
    mutationFn: () =>
      assignBlockCrop(blockId, {
        crop_id: cropId as string,
        crop_variety_id: varietyId,
        crop_variety_strain_id: strainId,
        season_label: season,
        effective_from: from,
        effective_to: to || null,
        planting_date: planting || null,
        attributes: buildPayload(attrDefs, attrValues),
        make_current: true,
      }),
    onSuccess: () => {
      setError(null);
      setCropId(null);
      setVarietyId(null);
      setStrainId(null);
      setSeason("");
      setTo("");
      setPlanting("");
      setCropPath(null);
      setAttrValues({});
      setShowHistory(true);
      void queryClient.invalidateQueries({ queryKey: ["block_crops", blockId] });
      onAssigned();
    },
    onError: (err: unknown) => {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("assignment.failed"));
    },
  });

  if (query.isLoading) {
    return <p className="text-[11px] text-ap-muted">{t("assignment.loading")}</p>;
  }

  return (
    <div>
      {/* ---- current ---- */}
      <div className="rounded-card border border-ap-line" data-testid="current-assignment">
        <header className="flex flex-wrap items-center gap-2 border-b border-ap-line bg-ap-bg px-3 py-1.5">
          <h4 className="text-[11px] font-semibold text-ap-ink">{t("assignment.current")}</h4>
          {current ? <StatePill state="current" /> : null}
          <div className="flex-1" />
          <label className="inline-flex cursor-pointer select-none items-center gap-1.5 text-[11px]">
            <input
              type="checkbox"
              checked={showHistory}
              onChange={(e) => setShowHistory(e.target.checked)}
            />
            {t("assignment.showHistory")}
          </label>
        </header>
        <div className="p-3">
          {current ? (
            <>
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-sm font-semibold text-ap-ink">{current.crop_path}</span>
                <span className="text-[11px] text-ap-muted">
                  {current.effective_from}
                  <span className="px-1">→</span>
                  {current.effective_to ?? t("assignment.ongoing")}
                </span>
                <span className="text-[11px] text-ap-muted">
                  · {humanDuration(current.effective_from, current.effective_to)}
                  {current.effective_to ? "" : ` ${t("assignment.soFar")}`}
                </span>
              </div>
              {/* Crop fields belong to *this* assignment, which is why they sit
                  inside the current card rather than beside the block. */}
              <CropAttributesCard blockCropId={current.id} farmId={farmId} />
            </>
          ) : (
            <p className="text-[11px] text-ap-muted">{t("assignment.none")}</p>
          )}
        </div>
      </div>

      {/* ---- history ---- */}
      {showHistory ? (
        <div className="mt-3 rounded-card border border-ap-line">
          <header className="flex items-center gap-2 border-b border-ap-line bg-ap-bg px-3 py-1.5">
            <h4 className="text-[11px] font-semibold text-ap-ink">{t("assignment.history")}</h4>
            <span className="text-meta text-ap-muted">
              {t("assignment.count", { count: rows.length })}
            </span>
          </header>
          <div className="p-3">
            {rows.length === 0 ? (
              <p className="text-[11px] text-ap-muted">{t("assignment.noHistory")}</p>
            ) : (
              <Table>
                <Thead>
                  <Tr>
                    <Th>{t("assignment.state")}</Th>
                    <Th>{t("assignment.crop")}</Th>
                    <Th>{t("assignment.range")}</Th>
                    <Th>{t("assignment.duration")}</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {rows.map((r) => (
                    <Tr
                      key={r.id}
                      className={stateOn(r, today) === "current" ? "bg-[#f4f9f3]" : ""}
                    >
                      <Td>
                        <StatePill state={stateOn(r, today)} />
                      </Td>
                      <Td className="font-medium">{r.crop_path}</Td>
                      <Td className="font-mono">
                        {r.effective_from}
                        <span className="px-1 text-ap-muted">→</span>
                        {r.effective_to ?? (
                          <span className="text-ap-muted">{t("assignment.ongoing")}</span>
                        )}
                      </Td>
                      <Td>{humanDuration(r.effective_from, r.effective_to)}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
            {/* A fallow block is legitimate, but it should be visible rather
                than left to be inferred from two dates that don't meet. */}
            {fallow.map((g) => (
              <p
                key={`${g.from}-${g.to}`}
                className="mt-2 rounded border-s-4 border-ap-warn bg-ap-warn-soft px-2 py-1 text-[11px]"
              >
                {t("assignment.fallow", {
                  from: g.from,
                  to: g.to,
                  days: humanDuration(g.from, g.to),
                })}
              </p>
            ))}
          </div>
        </div>
      ) : null}

      {/* ---- assign ---- */}
      {canAssign ? (
        <div className="mt-3 rounded-card border border-ap-line">
          <header className="flex items-center gap-2 border-b border-ap-line bg-ap-bg px-3 py-1.5">
            <h4 className="text-[11px] font-semibold text-ap-ink">{t("assignment.assignNew")}</h4>
          </header>
          <div className="p-3">
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
              onCropPathChange={(path) => {
                setCropPath(path);
                // Definitions differ per crop, so values from a previous
                // selection would be codes this crop has never heard of.
                setAttrValues({});
              }}
            />
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label={t("assignment.season")} required>
                {(a11y) => (
                  <input
                    {...a11y}
                    className={INPUT}
                    value={season}
                    onChange={(e) => setSeason(e.target.value)}
                    placeholder="2026"
                  />
                )}
              </Field>
              <Field label={t("assignment.from")} required>
                {(a11y) => (
                  <input
                    {...a11y}
                    type="date"
                    className={INPUT}
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                  />
                )}
              </Field>
              <Field
                label={t("assignment.to")}
                help={t("assignment.toHelp")}
                error={invertedRange ? t("assignment.inverted") : undefined}
              >
                {(a11y) => (
                  <input
                    {...a11y}
                    type="date"
                    className={INPUT}
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                  />
                )}
              </Field>
              <Field label={t("assignment.planting")} help={t("assignment.plantingHelp")}>
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
            </div>

            {/* Crop fields for the crop being assigned. They appear as soon as
                a crop is chosen and are saved with the assignment, so this is
                one screen rather than assign → save → come back and fill in. */}
            {attrVisible.length > 0 ? (
              <div className="mt-3 rounded-card border border-ap-line">
                <header className="border-b border-ap-line bg-ap-bg px-3 py-1.5">
                  <h5 className="text-[11px] font-semibold text-ap-ink">
                    {t("assignment.cropFields")}
                  </h5>
                </header>
                <div className="grid gap-3 p-3 sm:grid-cols-2">
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
                          attrMissing.includes(def.code) ? t("assignment.fieldRequired") : undefined
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
              </div>
            ) : null}

            {conflict ? (
              <p className="mt-3 rounded border-s-4 border-ap-crit bg-ap-crit-soft px-2 py-1 text-[11px]">
                {t("assignment.conflict", {
                  crop: conflict.crop_path,
                  from: conflict.effective_from,
                  to: conflict.effective_to ?? t("assignment.ongoing"),
                })}
              </p>
            ) : closing ? (
              <p className="mt-3 rounded border-s-4 border-ap-warn bg-ap-warn-soft px-2 py-1 text-[11px]">
                {t("assignment.willClose", { crop: closing.crop_path, date: from })}
              </p>
            ) : null}
            {error ? <p className="mt-2 text-[11px] text-ap-crit">{error}</p> : null}

            <div className="mt-3">
              <Button
                size="sm"
                disabled={!canSubmit || assign.isPending}
                onClick={() => assign.mutate()}
              >
                {assign.isPending ? t("assignment.assigning") : t("assignment.assign")}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StatePill({ state }: { state: ValidityState }): ReactNode {
  const { t } = useTranslation("farms");
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${STATE_PILL[state]}`}
    >
      {t(`assignment.stateLabel.${state}`)}
    </span>
  );
}
