import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { listInvestors, type HoldingFormStatus } from "@/api/investors";
import { FIELD_CONTROL_CLASS, Field } from "@/components/Field";
import { localizedName } from "@/lib/localizedField";

export interface HoldingFieldValues {
  code: string;
  name: string;
  name_ar: string;
  /** Kept as text so an empty box means "unknown", not 0. */
  tree_count: string;
  status: HoldingFormStatus;
  /** Used when status is "sold". */
  investor_id: string;
  owner_since: string;
  notes_internal: string;
}

interface Props {
  values: HoldingFieldValues;
  onChange: (values: HoldingFieldValues) => void;
  /** The code can be chosen on create only. */
  showCode?: boolean;
  /**
   * The holding already has an owner. Status then reads "Sold" with the
   * owner's name; a change of owner goes through the Ownership card.
   */
  currentOwner?: string | null;
}

/** The fields of a holding, shared by the new-holding and holding pages. */
export function HoldingFields({
  values,
  onChange,
  showCode = false,
  currentOwner = null,
}: Props): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const set = <K extends keyof HoldingFieldValues>(key: K, value: HoldingFieldValues[K]) =>
    onChange({ ...values, [key]: value });
  const selling = currentOwner === null && values.status === "sold";

  const investors = useQuery({
    queryKey: ["investors", "list", "picker"],
    queryFn: () => listInvestors(),
    enabled: selling,
  });

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {showCode ? (
        <Field label={t("holding.code")} help={t("holding.codeHelp")}>
          {(p) => (
            <input
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={values.code}
              maxLength={32}
              onChange={(e) => set("code", e.target.value)}
            />
          )}
        </Field>
      ) : null}
      <Field label={t("holding.name")} required>
        {(p) => (
          <input
            {...p}
            className={FIELD_CONTROL_CLASS}
            value={values.name}
            maxLength={200}
            required
            onChange={(e) => set("name", e.target.value)}
          />
        )}
      </Field>
      <Field label={t("holding.nameAr")}>
        {(p) => (
          <input
            {...p}
            dir="rtl"
            className={FIELD_CONTROL_CLASS}
            value={values.name_ar}
            maxLength={200}
            onChange={(e) => set("name_ar", e.target.value)}
          />
        )}
      </Field>
      <Field label={t("holding.trees")}>
        {(p) => (
          <input
            {...p}
            type="number"
            min={0}
            step={1}
            className={FIELD_CONTROL_CLASS}
            value={values.tree_count}
            onChange={(e) => set("tree_count", e.target.value)}
          />
        )}
      </Field>
      <Field label={t("holding.status")}>
        {(p) =>
          currentOwner !== null ? (
            <input
              {...p}
              readOnly
              className={FIELD_CONTROL_CLASS}
              value={`${t("holdingStatus.sold")} · ${currentOwner}`}
            />
          ) : (
            <select
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={values.status}
              onChange={(e) => set("status", e.target.value as HoldingFormStatus)}
            >
              <option value="draft">{t("holdingStatus.draft")}</option>
              <option value="available">{t("holdingStatus.available")}</option>
              <option value="sold">{t("holdingStatus.sold")}</option>
            </select>
          )
        }
      </Field>
      {selling ? (
        <>
          <Field label={t("newHolding.investor")} required>
            {(p) => (
              <select
                {...p}
                required
                className={FIELD_CONTROL_CLASS}
                value={values.investor_id}
                onChange={(e) => set("investor_id", e.target.value)}
              >
                <option value="">{t("newHolding.pickInvestor")}</option>
                {(investors.data ?? []).map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.code} · {localizedName(i18n.language, i.full_name, i.full_name_ar)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          {investors.isSuccess && investors.data.length === 0 ? (
            <p className="text-xs text-ap-warn sm:col-span-2">{t("newHolding.noInvestors")}</p>
          ) : null}
          <Field label={t("newHolding.ownerSince")} required>
            {(p) => (
              <input
                {...p}
                type="date"
                required
                className={FIELD_CONTROL_CLASS}
                value={values.owner_since}
                onChange={(e) => set("owner_since", e.target.value)}
              />
            )}
          </Field>
        </>
      ) : null}
      <Field label={t("holding.notes")} help={t("holding.notesHelp")} className="sm:col-span-2">
        {(p) => (
          <textarea
            {...p}
            rows={2}
            className={FIELD_CONTROL_CLASS}
            value={values.notes_internal}
            maxLength={4000}
            onChange={(e) => set("notes_internal", e.target.value)}
          />
        )}
      </Field>
    </div>
  );
}
