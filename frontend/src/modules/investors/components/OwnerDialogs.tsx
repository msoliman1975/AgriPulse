import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  listInvestors,
  type AcquiredBy,
  type EndedBy,
  type HoldingDetail,
  type Ownership,
  type OwnershipCreatePayload,
} from "@/api/investors";
import { Button } from "@/components/Button";
import { FIELD_CONTROL_CLASS, Field } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { localizedName } from "@/lib/localizedField";
import { dayBefore, isoDay } from "../lib";

const ACQUIRED: AcquiredBy[] = ["purchase", "transfer", "inheritance", "other"];
const ENDED: EndedBy[] = ["resale", "buyback", "contract_end", "correction", "other"];

interface AssignProps {
  open: boolean;
  holding: HoldingDetail;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (payload: OwnershipCreatePayload) => void;
}

/**
 * Give a holding an owner. When it already has an open-ended owner this is a
 * transfer: the server ends the old ownership on the day before the new start,
 * in the same transaction, and the dialog says so before the user saves.
 */
export function AssignOwnerDialog({
  open,
  holding,
  busy,
  error,
  onClose,
  onSubmit,
}: AssignProps): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const [investorId, setInvestorId] = useState("");
  const [startDate, setStartDate] = useState(isoDay());
  const [acquiredBy, setAcquiredBy] = useState<AcquiredBy>("purchase");
  const [contractRef, setContractRef] = useState("");
  const [previousEndedBy, setPreviousEndedBy] = useState<EndedBy>("resale");

  const investors = useQuery({
    queryKey: ["investors", "list", "picker"],
    queryFn: () => listInvestors(),
    enabled: open,
  });

  const openEnded = holding.ownerships.find((o) => o.end_date === null) ?? null;
  const choices = (investors.data ?? []).filter(
    (i) => i.status !== "archived" && i.id !== openEnded?.investor_id,
  );
  const title = openEnded
    ? t("owner.transferTitle", { code: holding.code })
    : t("owner.assignTitle", { code: holding.code });

  return (
    <Modal open={open} onClose={onClose} labelledBy="assign-owner-title" className="max-w-lg">
      <h2 id="assign-owner-title" className="text-lg font-semibold text-ap-ink">
        {title}
      </h2>
      <form
        className="mt-4 flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit({
            investor_id: investorId,
            start_date: startDate,
            acquired_by: acquiredBy,
            contract_ref: contractRef.trim() || null,
            previous_ended_by: previousEndedBy,
          });
        }}
      >
        <Field label={t("owner.investor")} required>
          {(p) => (
            <select
              {...p}
              required
              className={FIELD_CONTROL_CLASS}
              value={investorId}
              onChange={(e) => setInvestorId(e.target.value)}
            >
              <option value="">{t("owner.pickInvestor")}</option>
              {choices.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.code} · {localizedName(i18n.language, i.full_name, i.full_name_ar)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("owner.startDate")} required>
          {(p) => (
            <input
              {...p}
              type="date"
              required
              className={FIELD_CONTROL_CLASS}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("owner.acquiredBy")}>
          {(p) => (
            <select
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={acquiredBy}
              onChange={(e) => setAcquiredBy(e.target.value as AcquiredBy)}
            >
              {ACQUIRED.map((a) => (
                <option key={a} value={a}>
                  {t(`acquiredBy.${a}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("owner.contract")}>
          {(p) => (
            <input
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={contractRef}
              maxLength={120}
              onChange={(e) => setContractRef(e.target.value)}
            />
          )}
        </Field>
        {openEnded ? (
          <>
            <Field label={t("owner.previousEnd")}>
              {(p) => (
                <select
                  {...p}
                  className={FIELD_CONTROL_CLASS}
                  value={previousEndedBy}
                  onChange={(e) => setPreviousEndedBy(e.target.value as EndedBy)}
                >
                  {ENDED.map((a) => (
                    <option key={a} value={a}>
                      {t(`endedBy.${a}`)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <p className="rounded-md bg-ap-warn-soft p-2 text-sm text-ap-warn">
              {t("owner.transferNote", {
                name: localizedName(
                  i18n.language,
                  openEnded.investor_name,
                  openEnded.investor_name_ar,
                ),
                date: startDate ? dayBefore(startDate) : "—",
              })}
            </p>
          </>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-ap-crit">
            {error}
          </p>
        ) : null}
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("owner.cancel")}
          </Button>
          <Button type="submit" disabled={busy || !investorId || !startDate}>
            {t("owner.save")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

interface EndProps {
  ownership: Ownership | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (payload: { end_date: string; ended_by: EndedBy }) => void;
}

export function EndOwnershipDialog({
  ownership,
  busy,
  error,
  onClose,
  onSubmit,
}: EndProps): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const [endDate, setEndDate] = useState(isoDay());
  const [endedBy, setEndedBy] = useState<EndedBy>("contract_end");
  const name = ownership
    ? localizedName(i18n.language, ownership.investor_name, ownership.investor_name_ar)
    : "";

  return (
    <Modal
      open={ownership !== null}
      onClose={onClose}
      labelledBy="end-owner-title"
      className="max-w-md"
    >
      <h2 id="end-owner-title" className="text-lg font-semibold text-ap-ink">
        {t("owner.endTitle", { name })}
      </h2>
      <form
        className="mt-4 flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit({ end_date: endDate, ended_by: endedBy });
        }}
      >
        <Field label={t("owner.endDate")} required>
          {(p) => (
            <input
              {...p}
              type="date"
              required
              min={ownership?.start_date}
              className={FIELD_CONTROL_CLASS}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          )}
        </Field>
        <Field label={t("owner.endedBy")}>
          {(p) => (
            <select
              {...p}
              className={FIELD_CONTROL_CLASS}
              value={endedBy}
              onChange={(e) => setEndedBy(e.target.value as EndedBy)}
            >
              {ENDED.map((a) => (
                <option key={a} value={a}>
                  {t(`endedBy.${a}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        {error ? (
          <p role="alert" className="text-sm text-ap-crit">
            {error}
          </p>
        ) : null}
        <div className="mt-2 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("owner.cancel")}
          </Button>
          <Button type="submit" disabled={busy || !endDate}>
            {t("owner.save")}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
