// "Harvest" on the block page (build plan 3.5).
//
// One row per pick: date, weight and, once sold, the price per kilogram.
// Staff with `harvest.manage` add, correct and remove picks; holders of
// `harvest.read` see the list and its totals. The investor app shows each
// investor their share of these picks (PR 6); internal notes never leave
// this screen.

import { useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { HarvestLot, HarvestLotPayload } from "@/api/harvest";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { localizedName } from "@/lib/localizedField";
import { useDeleteHarvestLot, useHarvestLots, useSaveHarvestLot } from "@/queries/harvest";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  blockId: string;
  farmId: string;
}

function sum(values: (string | null)[]): number {
  return values.reduce((acc, v) => acc + (v ? Number(v) : 0), 0);
}

export function HarvestCard({ blockId, farmId }: Props): ReactNode {
  const { t, i18n } = useTranslation("farms");
  const canManage = useCapability("harvest.manage", { farmId });
  const lots = useHarvestLots(blockId);
  const remove = useDeleteHarvestLot(blockId);
  // null: no form; "new": adding; an id: editing that pick.
  const [editing, setEditing] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  const rows = lots.data ?? [];
  const currency = rows[0]?.currency ?? "";

  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-ap-ink">{t("harvest.heading")}</h2>
        {canManage && editing === null ? (
          <Button onClick={() => setEditing("new")}>{t("harvest.add")}</Button>
        ) : null}
      </div>

      {editing === "new" ? (
        <HarvestForm blockId={blockId} lot={null} onDone={() => setEditing(null)} />
      ) : null}

      {lots.isLoading ? (
        <p className="mt-2 text-sm text-ap-muted">{t("harvest.loading")}</p>
      ) : lots.isError ? (
        <p className="mt-2 text-sm text-ap-crit">{t("harvest.loadFailed")}</p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-sm text-ap-muted">{t("harvest.empty")}</p>
      ) : (
        <div className="mt-3">
          <Table>
            <Thead>
              <Tr>
                <Th className="py-1 text-start">{t("harvest.pick")}</Th>
                <Th className="py-1 text-start">{t("harvest.date")}</Th>
                <Th className="py-1 text-end">{t("harvest.weight")}</Th>
                <Th className="py-1 text-end">{t("harvest.price")}</Th>
                <Th className="py-1 text-end">{t("harvest.revenue")}</Th>
                {canManage ? <Th /> : null}
              </Tr>
            </Thead>
            <Tbody>
              {rows.map((lot) =>
                editing === lot.id ? (
                  <Tr key={lot.id}>
                    <Td colSpan={canManage ? 6 : 5}>
                      <HarvestForm blockId={blockId} lot={lot} onDone={() => setEditing(null)} />
                    </Td>
                  </Tr>
                ) : (
                  <Tr key={lot.id}>
                    <Td className="py-1">
                      {t("harvest.pickN", { n: lot.pick_no })}
                      {lot.label || lot.label_ar ? (
                        <span className="ms-1 text-ap-muted">
                          {localizedName(
                            i18n.language,
                            lot.label ?? lot.label_ar ?? "",
                            lot.label_ar,
                          )}
                        </span>
                      ) : null}
                      <span className="block text-[11px] text-ap-muted">{lot.season_label}</span>
                    </Td>
                    <Td className="py-1">{lot.harvested_on}</Td>
                    <Td className="py-1 text-end">{number.format(Number(lot.weight_kg))}</Td>
                    <Td className="py-1 text-end">
                      {lot.price_per_kg ? number.format(Number(lot.price_per_kg)) : "—"}
                    </Td>
                    <Td className="py-1 text-end">
                      {lot.revenue ? `${number.format(Number(lot.revenue))} ${lot.currency}` : "—"}
                    </Td>
                    {canManage ? (
                      <Td className="py-1 text-end">
                        {confirmDelete === lot.id ? (
                          <span className="inline-flex gap-1">
                            <button
                              type="button"
                              className="text-xs text-ap-crit"
                              disabled={remove.isPending}
                              onClick={() =>
                                remove.mutate(lot.id, { onSettled: () => setConfirmDelete(null) })
                              }
                            >
                              {t("harvest.confirmDelete")}
                            </button>
                            <button
                              type="button"
                              className="text-xs text-ap-muted"
                              onClick={() => setConfirmDelete(null)}
                            >
                              {t("harvest.cancel")}
                            </button>
                          </span>
                        ) : (
                          <span className="inline-flex gap-2">
                            <button
                              type="button"
                              className="text-xs text-ap-primary"
                              onClick={() => setEditing(lot.id)}
                            >
                              {t("harvest.edit")}
                            </button>
                            <button
                              type="button"
                              className="text-xs text-ap-muted"
                              onClick={() => setConfirmDelete(lot.id)}
                            >
                              {t("harvest.delete")}
                            </button>
                          </span>
                        )}
                      </Td>
                    ) : null}
                  </Tr>
                ),
              )}
            </Tbody>
          </Table>
          <p className="mt-2 text-sm font-medium text-ap-ink">
            {t("harvest.totals", {
              weight: number.format(sum(rows.map((r) => r.weight_kg))),
              revenue: number.format(sum(rows.map((r) => r.revenue))),
              currency,
            })}
          </p>
          <p className="mt-1 text-[11px] text-ap-muted">{t("harvest.unitsHint")}</p>
        </div>
      )}
    </Card>
  );
}

function HarvestForm({
  blockId,
  lot,
  onDone,
}: {
  blockId: string;
  lot: HarvestLot | null;
  onDone: () => void;
}): ReactNode {
  const { t } = useTranslation("farms");
  const save = useSaveHarvestLot(blockId);
  const [harvestedOn, setHarvestedOn] = useState(lot?.harvested_on ?? "");
  const [weight, setWeight] = useState(lot?.weight_kg ?? "");
  const [price, setPrice] = useState(lot?.price_per_kg ?? "");
  const [label, setLabel] = useState(lot?.label ?? "");
  const [labelAr, setLabelAr] = useState(lot?.label_ar ?? "");
  const [notes, setNotes] = useState(lot?.notes_internal ?? "");
  const [error, setError] = useState<string | null>(null);

  const submit = (e: FormEvent): void => {
    e.preventDefault();
    if (!harvestedOn || !(Number(weight) > 0)) {
      setError(t("harvest.needDateWeight"));
      return;
    }
    setError(null);
    const payload: HarvestLotPayload = {
      harvested_on: harvestedOn,
      weight_kg: weight,
      price_per_kg: price === "" ? null : price,
      label: label || null,
      label_ar: labelAr || null,
      notes_internal: notes || null,
    };
    save.mutate(
      { lotId: lot?.id ?? null, payload },
      {
        onSuccess: onDone,
        onError: () => setError(t("harvest.saveFailed")),
      },
    );
  };

  return (
    <form onSubmit={submit} className="mt-3 grid gap-2 sm:grid-cols-3">
      <label className="text-xs text-ap-muted">
        {t("harvest.date")}
        <input
          type="date"
          className="mt-1 block w-full rounded border border-ap-line px-2 py-1 text-sm text-ap-ink"
          value={harvestedOn}
          onChange={(e) => setHarvestedOn(e.target.value)}
        />
      </label>
      <label className="text-xs text-ap-muted">
        {t("harvest.weight")}
        <input
          inputMode="decimal"
          className="mt-1 block w-full rounded border border-ap-line px-2 py-1 text-sm text-ap-ink"
          value={weight}
          onChange={(e) => setWeight(e.target.value)}
        />
      </label>
      <label className="text-xs text-ap-muted">
        {t("harvest.price")}
        <input
          inputMode="decimal"
          className="mt-1 block w-full rounded border border-ap-line px-2 py-1 text-sm text-ap-ink"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
        />
      </label>
      <label className="text-xs text-ap-muted">
        {t("harvest.label")}
        <input
          className="mt-1 block w-full rounded border border-ap-line px-2 py-1 text-sm text-ap-ink"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
      </label>
      <label className="text-xs text-ap-muted">
        {t("harvest.labelAr")}
        <input
          dir="rtl"
          className="mt-1 block w-full rounded border border-ap-line px-2 py-1 text-sm text-ap-ink"
          value={labelAr}
          onChange={(e) => setLabelAr(e.target.value)}
        />
      </label>
      <label className="text-xs text-ap-muted">
        {t("harvest.notes")}
        <input
          className="mt-1 block w-full rounded border border-ap-line px-2 py-1 text-sm text-ap-ink"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      {error ? (
        <p role="alert" className="text-xs text-ap-crit sm:col-span-3">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? t("harvest.saving") : t("harvest.save")}
        </Button>
        <button type="button" className="text-sm text-ap-muted" onClick={onDone}>
          {t("harvest.cancel")}
        </button>
      </div>
    </form>
  );
}
