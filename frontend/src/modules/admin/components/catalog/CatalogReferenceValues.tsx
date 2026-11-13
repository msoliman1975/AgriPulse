// The catalogue's Reference values tab (decisions D18 and D23).
//
// Salt tolerance, expected yield and load, and spacing, typed by key. A path
// sets only what differs from the level above; every other value shows what
// it inherits and from where. Each value can carry its sources (D27).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  deleteReferenceValue,
  formatReference,
  getReferenceValues,
  listReferenceKeys,
  putReferenceValue,
  type ReferenceGroup,
  type ReferenceKey,
  type ReferenceView,
} from "@/api/referenceValues";
import { Button } from "@/components/Button";
import { FIELD_CONTROL_CLASS } from "@/components/Field";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { SourcesMarker } from "@/modules/sources/SourcesMarker";

const GROUPS: readonly ReferenceGroup[] = ["salinity", "yield", "spacing"];

export function ReferenceValuesPanel({
  cropPath,
  canManage,
}: {
  cropPath: string;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const keys = useQuery({ queryKey: ["reference-values", "keys"], queryFn: listReferenceKeys });
  const view = useQuery({
    queryKey: ["reference-values", cropPath],
    queryFn: () => getReferenceValues(cropPath),
  });

  if (keys.isLoading || view.isLoading) {
    return <p className="text-xs text-ap-muted">{t("crops.loading")}</p>;
  }
  if (keys.isError || view.isError || !keys.data || !view.data) {
    return <StatusBanner kind="crit">{t("catalog.reference.loadFailed")}</StatusBanner>;
  }

  return (
    <section className="space-y-5">
      <p className="text-[11px] text-ap-muted">{t("catalog.reference.intro")}</p>
      {GROUPS.map((group) => (
        <div key={group} className="space-y-2">
          <h3 className="text-xs font-medium text-ap-ink">
            {t(`catalog.reference.group.${group}`)}
          </h3>
          <ul className="divide-y divide-ap-line rounded-md border border-ap-line">
            {keys.data
              .filter((k) => k.group === group)
              .map((k) => (
                <ValueRow
                  key={k.key}
                  spec={k}
                  view={view.data}
                  cropPath={cropPath}
                  canManage={canManage}
                />
              ))}
            {group === "spacing" ? (
              <li className="flex items-center gap-2 px-3 py-2 text-sm">
                <span className="text-ap-ink">{t("catalog.reference.key.plants_per_ha")}</span>
                <span className="ms-auto font-mono text-xs">{view.data.plants_per_ha ?? "—"}</span>
                <Pill kind="neutral">{t("catalog.reference.derived")}</Pill>
              </li>
            ) : null}
          </ul>
        </div>
      ))}
    </section>
  );
}

function ValueRow({
  spec,
  view,
  cropPath,
  canManage,
}: {
  spec: ReferenceKey;
  view: ReferenceView;
  cropPath: string;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const client = useQueryClient();
  const resolved = view.resolved[spec.key];
  const own = view.own.find((r) => r.key === spec.key) ?? null;
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(own?.value != null ? String(Number(own.value)) : "");
  const [lo, setLo] = useState(own?.value_min != null ? String(Number(own.value_min)) : "");
  const [hi, setHi] = useState(own?.value_max != null ? String(Number(own.value_max)) : "");
  const [note, setNote] = useState(own?.note ?? "");

  const refresh = () => void client.invalidateQueries({ queryKey: ["reference-values", cropPath] });
  const num = (s: string): number | null => (s.trim() === "" ? null : Number(s));
  const save = useMutation({
    mutationFn: () =>
      putReferenceValue(cropPath, spec.key, {
        value: num(value),
        value_min: num(lo),
        value_max: num(hi),
        note: note.trim() || null,
      }),
    onSuccess: () => {
      setEditing(false);
      refresh();
    },
  });
  const clear = useMutation({
    mutationFn: () => deleteReferenceValue(cropPath, spec.key),
    onSuccess: refresh,
  });

  return (
    <li className="flex flex-col gap-2 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-ap-ink">{t(`catalog.reference.key.${spec.key}`)}</span>
        <span className="text-[11px] text-ap-muted">{spec.unit}</span>
        <span className="ms-auto font-mono text-xs">
          {resolved ? formatReference(resolved) : "—"}
        </span>
        {resolved && resolved.from_path !== cropPath ? (
          <Pill kind="neutral">
            {t("catalog.reference.inherited", { path: resolved.from_path })}
          </Pill>
        ) : null}
        {resolved ? (
          <SourcesMarker
            entityType="reference_value"
            entityKey={`${resolved.from_path}#${spec.key}`}
          />
        ) : null}
        {canManage && !editing ? (
          <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
            {own ? t("catalog.reference.edit") : t("catalog.reference.set")}
          </Button>
        ) : null}
        {canManage && own && !editing ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={clear.isPending}
            onClick={() => clear.mutate()}
          >
            {t("catalog.reference.clear")}
          </Button>
        ) : null}
      </div>
      {resolved?.note ? <p className="text-[11px] text-ap-muted">{resolved.note}</p> : null}
      {editing ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          {(
            [
              ["value", value, setValue],
              ["min", lo, setLo],
              ["max", hi, setHi],
            ] as const
          ).map(([label, v, set]) => (
            <label key={label} className="flex flex-col gap-1 text-[11px] text-ap-muted">
              {t(`catalog.reference.${label}`)}
              <input
                className={`${FIELD_CONTROL_CLASS} w-24`}
                inputMode="decimal"
                value={v}
                onChange={(e) => set(e.target.value)}
              />
            </label>
          ))}
          <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-[11px] text-ap-muted">
            {t("catalog.reference.note")}
            <input
              className={FIELD_CONTROL_CLASS}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <Button type="submit" size="sm" disabled={save.isPending || (!value && !lo && !hi)}>
            {t("catalog.reference.save")}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)}>
            {t("catalog.reference.cancel")}
          </Button>
          {save.isError ? (
            <StatusBanner kind="crit">{t("catalog.reference.saveFailed")}</StatusBanner>
          ) : null}
        </form>
      ) : null}
    </li>
  );
}
