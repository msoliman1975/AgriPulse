import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getBlockCropAttributeHistory,
  getBlockCropAttributes,
  putBlockCropAttributes,
} from "@/api/cropAssignments";
import type { CropAttributeDefinition } from "@/api/crops";
import { isApiError } from "@/api/errors";
import { Button } from "@/components/Button";
import { Field } from "@/components/Field";
import {
  buildPayload,
  clearedByGate,
  formatValue,
  groupDefinitions,
  isRequired,
  label,
  missingRequired,
  visibleDefinitions,
  type AttributeValues,
} from "@/modules/farms/lib/cropAttributeForm";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  /** `block_crops.id` of the assignment being edited. */
  blockCropId: string;
  farmId: string;
}

const INPUT =
  "block w-full rounded-md border border-ap-line bg-white px-2 py-1 text-xs text-ap-ink";

/**
 * The crop-attributes section of a crop → block assignment.
 *
 * Renders the platform-curated fields for this block's crop — establishment
 * method, transplant date, age at transplant, seed grade, whatever the catalog
 * defines — grouped, gated live, and saved as one form.
 *
 * Definitions arrive with the values in a single response, so the form never
 * renders a field the server would not accept. Gating is evaluated client-side
 * for responsiveness only; the server re-validates every save and is
 * authoritative.
 */
export function CropAttributesCard({ blockCropId, farmId }: Props): ReactNode {
  const { t, i18n } = useTranslation("farms");
  const canEdit = useCapability("block.update_metadata", { farmId });
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["crop_attributes", blockCropId] as const,
    queryFn: () => getBlockCropAttributes(blockCropId),
  });

  const [values, setValues] = useState<AttributeValues>({});
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [historyFor, setHistoryFor] = useState<string | null>(null);

  // Re-seed the form whenever the server's copy changes (first load, save,
  // switching blocks). Guarded on `dirty` so a refetch mid-edit cannot discard
  // what the user has typed.
  useEffect(() => {
    if (query.data && !dirty) setValues({ ...query.data.values });
  }, [query.data, dirty]);

  const definitions = useMemo(() => query.data?.definitions ?? [], [query.data]);
  const visible = useMemo(() => visibleDefinitions(definitions, values), [definitions, values]);
  const missing = useMemo(() => missingRequired(definitions, values), [definitions, values]);
  const willClear = useMemo(() => clearedByGate(definitions, values), [definitions, values]);

  const save = useMutation({
    mutationFn: () => putBlockCropAttributes(blockCropId, buildPayload(definitions, values)),
    onSuccess: (data) => {
      setDirty(false);
      setError(null);
      setValues({ ...data.values });
      queryClient.setQueryData(["crop_attributes", blockCropId], data);
      void queryClient.invalidateQueries({
        queryKey: ["crop_attributes", blockCropId, "history"],
      });
    },
    onError: (err: unknown) => {
      setError(
        isApiError(err) ? (err.problem.detail ?? err.message) : t("cropAttributes.saveFailed"),
      );
    },
  });

  const setValue = (code: string, value: unknown): void => {
    setDirty(true);
    setValues((prev) => ({ ...prev, [code]: value }));
  };

  if (query.isLoading) {
    return <p className="text-[11px] text-ap-muted">{t("cropAttributes.loading")}</p>;
  }
  // A crop with no attributes defined renders nothing at all — an empty
  // "Crop fields" heading on every non-tree block would be pure noise.
  if (query.isError || definitions.length === 0) return null;

  const groups = groupDefinitions(visible);
  const lang = i18n.language;

  return (
    <div className="mt-2">
      {groups.map((group) => (
        <div key={group.code} className="mt-2 rounded-card border border-ap-line">
          <header className="flex items-center gap-2 border-b border-ap-line bg-ap-bg px-3 py-1.5">
            <h4 className="text-[11px] font-semibold text-ap-ink">
              {group.nameEn
                ? label({ name_en: group.nameEn, name_ar: group.nameAr }, lang)
                : t("cropAttributes.otherGroup")}
            </h4>
            <span className="text-meta text-ap-muted">
              {group.defs.length}/
              {definitions.filter((d) => (d.group_code ?? "") === group.code).length}
            </span>
          </header>
          <div className="grid gap-3 p-3 sm:grid-cols-2">
            {group.defs.map((def) => (
              <AttributeField
                key={def.code}
                def={def}
                value={values[def.code]}
                required={isRequired(def, values)}
                missing={missing.includes(def.code)}
                readOnly={!canEdit}
                lang={lang}
                onChange={(v) => setValue(def.code, v)}
                onShowHistory={() => setHistoryFor(def.code)}
              />
            ))}
          </div>
        </div>
      ))}

      {willClear.length > 0 ? (
        <p className="mt-2 rounded border-s-4 border-ap-warn bg-ap-warn-soft px-2 py-1 text-[11px] text-ap-ink">
          {t("cropAttributes.willClear", { fields: willClear.join(", ") })}
        </p>
      ) : null}
      {error ? <p className="mt-2 text-[11px] text-ap-crit">{error}</p> : null}

      {canEdit ? (
        <div className="mt-2 flex items-center gap-2">
          <Button
            size="sm"
            disabled={!dirty || missing.length > 0 || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? t("cropAttributes.saving") : t("cropAttributes.save")}
          </Button>
          {dirty ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setDirty(false);
                setError(null);
                setValues({ ...(query.data?.values ?? {}) });
              }}
            >
              {t("cropAttributes.reset")}
            </Button>
          ) : null}
          {missing.length > 0 ? (
            <span className="text-[11px] text-ap-crit">
              {t("cropAttributes.missingRequired", { fields: missing.join(", ") })}
            </span>
          ) : null}
        </div>
      ) : null}

      {historyFor ? (
        <AttributeHistory
          blockCropId={blockCropId}
          def={definitions.find((d) => d.code === historyFor)}
          code={historyFor}
          lang={lang}
          onClose={() => setHistoryFor(null)}
        />
      ) : null}
    </div>
  );
}

interface FieldProps {
  def: CropAttributeDefinition;
  value: unknown;
  required: boolean;
  missing: boolean;
  readOnly: boolean;
  lang: string;
  onChange: (value: unknown) => void;
  onShowHistory: () => void;
}

function AttributeField({
  def,
  value,
  required,
  missing,
  readOnly,
  lang,
  onChange,
  onShowHistory,
}: FieldProps): ReactNode {
  const { t } = useTranslation("farms");
  const unit = lang.startsWith("ar") ? def.unit_ar : def.unit_en;
  const description = lang.startsWith("ar") ? def.description_ar : def.description_en;
  const range =
    def.value_min !== null && def.value_max !== null ? `${def.value_min}–${def.value_max}` : null;

  const help = (
    <>
      {description}
      {range ? <span className="ms-1 text-ap-muted">({range})</span> : null}{" "}
      <button
        type="button"
        onClick={onShowHistory}
        className="text-ap-accent underline decoration-dotted"
      >
        {t("cropAttributes.history")}
      </button>
    </>
  );

  return (
    <Field
      label={
        <span>
          {label(def, lang)}
          {unit ? <span className="ms-1 text-ap-muted">({unit})</span> : null}
        </span>
      }
      required={required}
      help={help}
      error={missing ? t("cropAttributes.requiredForThis") : undefined}
      className={def.value_type === "multi_select" ? "sm:col-span-2" : undefined}
    >
      {(a11y) => (
        <AttributeInput
          def={def}
          value={value}
          readOnly={readOnly}
          lang={lang}
          onChange={onChange}
          a11y={a11y}
        />
      )}
    </Field>
  );
}

interface InputProps {
  def: CropAttributeDefinition;
  value: unknown;
  readOnly: boolean;
  lang: string;
  onChange: (value: unknown) => void;
  a11y: { id: string; "aria-describedby": string | undefined; "aria-invalid": boolean | undefined };
}

function AttributeInput({ def, value, readOnly, lang, onChange, a11y }: InputProps): ReactNode {
  const { t } = useTranslation("farms");
  const options = def.options ?? [];

  if (def.value_type === "single_select") {
    return (
      <select
        {...a11y}
        className={INPUT}
        disabled={readOnly}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">{t("cropAttributes.selectPlaceholder")}</option>
        {options.map((o) => (
          <option key={o.code} value={o.code}>
            {label(o, lang)}
          </option>
        ))}
      </select>
    );
  }

  if (def.value_type === "multi_select") {
    const chosen = new Set(Array.isArray(value) ? (value as string[]) : []);
    return (
      <div {...a11y} className="flex flex-wrap gap-3 pt-1">
        {options.map((o) => (
          <label key={o.code} className="inline-flex items-center gap-1.5 text-xs">
            <input
              type="checkbox"
              disabled={readOnly}
              checked={chosen.has(o.code)}
              onChange={(e) => {
                const next = new Set(chosen);
                if (e.target.checked) next.add(o.code);
                else next.delete(o.code);
                // An empty selection is absence, not an empty array — the
                // server's options_non_empty CHECK rejects the latter.
                onChange(next.size ? [...next] : null);
              }}
            />
            {label(o, lang)}
          </label>
        ))}
      </div>
    );
  }

  if (def.value_type === "boolean") {
    return (
      <input
        {...a11y}
        type="checkbox"
        disabled={readOnly}
        checked={value === true}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  }

  if (def.value_type === "date") {
    return (
      <input
        {...a11y}
        type="date"
        className={INPUT}
        disabled={readOnly}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      />
    );
  }

  if (def.value_type === "integer" || def.value_type === "decimal") {
    return (
      <input
        {...a11y}
        type="number"
        className={INPUT}
        disabled={readOnly}
        step={def.value_type === "integer" ? 1 : 10 ** -(def.decimal_places ?? 1)}
        min={def.value_min ?? undefined}
        max={def.value_max ?? undefined}
        // The API returns numerics as decimal strings (Numeric(14,4)), so this
        // is a string or a number — never an object.
        value={typeof value === "number" || typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
      />
    );
  }

  return (
    <input
      {...a11y}
      type="text"
      className={INPUT}
      disabled={readOnly}
      maxLength={def.text_max_length ?? 500}
      value={(value as string) ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
    />
  );
}

function AttributeHistory({
  blockCropId,
  def,
  code,
  lang,
  onClose,
}: {
  blockCropId: string;
  /** Used to map stored option codes back to their localised label. */
  def: CropAttributeDefinition | undefined;
  code: string;
  lang: string;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("farms");
  const history = useQuery({
    queryKey: ["crop_attributes", blockCropId, "history", code] as const,
    queryFn: () => getBlockCropAttributeHistory(blockCropId, code),
  });

  return (
    <div className="mt-2 rounded-card border border-ap-line p-3">
      <div className="flex items-center gap-2">
        <h4 className="text-[11px] font-semibold text-ap-ink">
          {t("cropAttributes.historyFor", { code })}
        </h4>
        <div className="flex-1" />
        <Button size="sm" variant="secondary" onClick={onClose}>
          {t("cropAttributes.close")}
        </Button>
      </div>
      {history.isLoading ? (
        <p className="mt-1 text-[11px] text-ap-muted">{t("cropAttributes.loading")}</p>
      ) : (history.data?.length ?? 0) === 0 ? (
        <p className="mt-1 text-[11px] text-ap-muted">{t("cropAttributes.noHistory")}</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {history.data?.map((h) => (
            <li key={h.id} className="text-[11px] text-ap-ink">
              {h.previous_value !== null && h.previous_value !== undefined ? (
                <>
                  <span className="font-medium">{formatValue(h.previous_value, def, lang)}</span>
                  <span className="px-1 text-ap-muted">→</span>
                </>
              ) : null}
              <span className="font-medium">{formatValue(h.value, def, lang)}</span>
              <span className="ms-2 text-meta text-ap-muted">
                {t(`cropAttributes.changeKind.${h.change_kind}`)} · {h.changed_at.slice(0, 16)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
