import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO, type Locale } from "date-fns";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { listBlocks } from "@/api/blocks";
import { Modal } from "@/components/Modal";
import {
  listSignalObservations,
  type SignalDefinition,
  type SignalObservation,
} from "@/api/signals";
import { useDateLocale } from "@/hooks/useDateLocale";
import {
  useDeleteSignalObservation,
  useDeleteSignalTemplateObservationGroup,
} from "@/queries/signals";

import { _internals as dateInternals } from "./ObservedAtPicker";

const PAGE_SIZE = 50;
const MAX_LOADED = 500;

const inputCls =
  "rounded-md border border-ap-line bg-white px-2 py-1 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary";

interface Props {
  farmId: string;
  definitions: SignalDefinition[];
  canDelete: boolean;
}

interface Filters {
  definitionId: string; // "" = all
  blockId: string; // "" = any
  since: string | null; // ISO
  until: string | null; // ISO
  templatedOnly: boolean;
}

function defaultSince(): string {
  return new Date(Date.now() - 30 * 86_400_000).toISOString();
}

// A render item is either a standalone observation or a templated group.
type ListItem =
  | { kind: "single"; obs: SignalObservation }
  | { kind: "group"; tid: string; rows: SignalObservation[] };

function groupObservations(rows: SignalObservation[]): ListItem[] {
  const items: ListItem[] = [];
  const groupIndex = new Map<string, number>();
  for (const obs of rows) {
    const tid = obs.template_observation_id ?? null;
    if (!tid) {
      items.push({ kind: "single", obs });
      continue;
    }
    const existing = groupIndex.get(tid);
    if (existing === undefined) {
      groupIndex.set(tid, items.length);
      items.push({ kind: "group", tid, rows: [obs] });
    } else {
      (items[existing] as { kind: "group"; tid: string; rows: SignalObservation[] }).rows.push(obs);
    }
  }
  return items;
}

function formatValue(o: SignalObservation): string {
  if (o.value_numeric !== null) return o.value_numeric;
  if (o.value_categorical !== null) return o.value_categorical;
  if (o.value_event !== null) return o.value_event;
  if (o.value_boolean !== null) return String(o.value_boolean);
  if (o.value_geopoint) return `${o.value_geopoint.latitude}, ${o.value_geopoint.longitude}`;
  return "—";
}

export function ObservationList({ farmId, definitions, canDelete }: Props): ReactNode {
  const { t } = useTranslation("signals");
  const dateLocale = useDateLocale();

  const [filters, setFilters] = useState<Filters>({
    definitionId: "",
    blockId: "",
    since: defaultSince(),
    until: null,
    templatedOnly: false,
  });
  const setFilter = <K extends keyof Filters>(k: K, v: Filters[K]) =>
    setFilters((f) => ({ ...f, [k]: v }));

  const defName = useMemo(() => {
    const m = new Map<string, string>();
    for (const d of definitions) m.set(d.id, d.name);
    return m;
  }, [definitions]);

  const blocksQ = useQuery({
    queryKey: ["blocks", "list", farmId] as const,
    queryFn: () => listBlocks(farmId),
    enabled: Boolean(farmId),
    staleTime: 60_000,
  });
  const blocks = blocksQ.data?.items ?? [];

  const deleteOne = useDeleteSignalObservation();
  const deleteGroup = useDeleteSignalTemplateObservationGroup();

  // Server-side filters go in the query key so changing them refetches
  // from page 1. `templatedOnly` is a client-side view filter applied
  // after fetch, so it stays out of the key.
  const serverFilters = {
    definitionId: filters.definitionId,
    blockId: filters.blockId,
    since: filters.since,
    until: filters.until,
  };

  const obsQuery = useInfiniteQuery({
    queryKey: ["signal_observations", "paged", farmId, serverFilters] as const,
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      // Page back through time: pass the oldest loaded `time` as the next
      // `until` (API returns most-recent-first). First page uses the filter.
      listSignalObservations({
        farm_id: farmId,
        signal_definition_id: filters.definitionId || undefined,
        block_id: filters.blockId || undefined,
        since: filters.since ?? undefined,
        until: pageParam ?? filters.until ?? undefined,
        limit: PAGE_SIZE,
      }),
    getNextPageParam: (lastPage) =>
      lastPage.length === PAGE_SIZE ? lastPage[lastPage.length - 1].time : undefined,
  });

  const allRows = useMemo(
    () => (obsQuery.data?.pages ?? []).flat(),
    [obsQuery.data],
  );
  const viewRows = filters.templatedOnly
    ? allRows.filter((o) => o.template_observation_id)
    : allRows;
  const items = useMemo(() => groupObservations(viewRows), [viewRows]);
  const atCap = allRows.length >= MAX_LOADED;

  const [confirm, setConfirm] = useState<
    { kind: "single"; id: string } | { kind: "group"; tid: string; count: number } | null
  >(null);

  const runDelete = () => {
    if (!confirm) return;
    const opts = { onSuccess: () => setConfirm(null) };
    if (confirm.kind === "single") {
      deleteOne.mutate({ observationId: confirm.id }, opts);
    } else {
      deleteGroup.mutate({ templateObservationId: confirm.tid }, opts);
    }
  };
  const deleting = deleteOne.isPending || deleteGroup.isPending;

  return (
    <div className="rounded-xl border border-ap-line bg-ap-panel">
      <div className="flex items-center justify-between border-b border-ap-line px-4 py-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-ap-muted">
          {t("log.list.heading")}
        </span>
        <span className="text-[11px] text-ap-muted">
          {t("log.list.loadedCount", { count: allRows.length })}
        </span>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-end gap-2 border-b border-ap-line px-4 py-2 text-xs">
        <label className="flex flex-col gap-0.5">
          <span className="text-ap-muted">{t("log.list.filters.definition")}</span>
          <select
            value={filters.definitionId}
            onChange={(e) => setFilter("definitionId", e.target.value)}
            className={inputCls}
          >
            <option value="">{t("log.list.filters.allDefinitions")}</option>
            {definitions.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-ap-muted">{t("log.list.filters.block")}</span>
          <select
            value={filters.blockId}
            onChange={(e) => setFilter("blockId", e.target.value)}
            className={inputCls}
          >
            <option value="">{t("log.list.filters.anyBlock")}</option>
            {blocks.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-ap-muted">{t("log.list.filters.since")}</span>
          <input
            type="datetime-local"
            value={filters.since ? dateInternals.isoToLocalInput(filters.since) : ""}
            onChange={(e) => setFilter("since", dateInternals.localInputToIso(e.target.value))}
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-0.5">
          <span className="text-ap-muted">{t("log.list.filters.until")}</span>
          <input
            type="datetime-local"
            value={filters.until ? dateInternals.isoToLocalInput(filters.until) : ""}
            onChange={(e) => setFilter("until", dateInternals.localInputToIso(e.target.value))}
            className={inputCls}
          />
        </label>
        <label className="flex items-center gap-1.5 pb-1 text-ap-ink">
          <input
            type="checkbox"
            checked={filters.templatedOnly}
            onChange={(e) => setFilter("templatedOnly", e.target.checked)}
          />
          {t("log.list.filters.templatedOnly")}
        </label>
      </div>

      {obsQuery.isLoading ? (
        <p className="p-6 text-center text-xs text-ap-muted">{t("common.loading", { defaultValue: "Loading…" })}</p>
      ) : items.length === 0 ? (
        <p className="p-6 text-center text-xs text-ap-muted">{t("log.list.empty")}</p>
      ) : (
        <ul className="divide-y divide-ap-line">
          {items.map((item) =>
            item.kind === "single" ? (
              <ObservationRow
                key={item.obs.id}
                obs={item.obs}
                dateLocale={dateLocale}
                canDelete={canDelete}
                onDelete={() => setConfirm({ kind: "single", id: item.obs.id })}
              />
            ) : (
              <GroupRow
                key={item.tid}
                rows={item.rows}
                defName={defName}
                dateLocale={dateLocale}
                canDelete={canDelete}
                onDelete={() =>
                  setConfirm({ kind: "group", tid: item.tid, count: item.rows.length })
                }
              />
            ),
          )}
        </ul>
      )}

      {/* Pagination */}
      <div className="flex items-center justify-center gap-3 border-t border-ap-line px-4 py-2 text-xs">
        {atCap ? (
          <span className="text-amber-700">{t("log.list.capReached", { max: MAX_LOADED })}</span>
        ) : obsQuery.hasNextPage ? (
          <button
            type="button"
            onClick={() => void obsQuery.fetchNextPage()}
            disabled={obsQuery.isFetchingNextPage}
            className="rounded-md border border-ap-line bg-white px-3 py-1 font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
          >
            {obsQuery.isFetchingNextPage
              ? t("common.loading", { defaultValue: "Loading…" })
              : t("log.list.loadMore")}
          </button>
        ) : items.length > 0 ? (
          <span className="text-ap-muted">{t("log.list.allLoaded")}</span>
        ) : null}
      </div>

      {confirm ? (
        <DeleteConfirm
          count={confirm.kind === "group" ? confirm.count : 1}
          pending={deleting}
          onCancel={() => setConfirm(null)}
          onConfirm={runDelete}
        />
      ) : null}
    </div>
  );
}

function ObservationRow({
  obs,
  dateLocale,
  canDelete,
  onDelete,
}: {
  obs: SignalObservation;
  dateLocale: Locale;
  canDelete: boolean;
  onDelete: () => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  return (
    <li className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm">
      <span className="font-mono text-xs text-ap-muted">{obs.signal_code}</span>
      <span className="font-medium text-ap-ink">{formatValue(obs)}</span>
      {obs.notes ? <span className="text-xs text-ap-muted">— {obs.notes}</span> : null}
      <LocationChip obs={obs} />
      <span className="ms-auto text-[11px] text-ap-muted">
        {formatDistanceToNow(parseISO(obs.time), { addSuffix: true, locale: dateLocale })}
      </span>
      {obs.attachment_download_url ? (
        <a
          href={obs.attachment_download_url}
          target="_blank"
          rel="noreferrer"
          className="text-[11px] font-medium text-ap-primary hover:underline"
        >
          {t("log.list.photo")}
        </a>
      ) : null}
      {canDelete ? <DeleteButton onClick={onDelete} /> : null}
    </li>
  );
}

function GroupRow({
  rows,
  defName,
  dateLocale,
  canDelete,
  onDelete,
}: {
  rows: SignalObservation[];
  defName: Map<string, string>;
  dateLocale: Locale;
  canDelete: boolean;
  onDelete: () => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  const [open, setOpen] = useState(false);
  const lead = rows[0];
  return (
    <li className="px-4 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-1 text-ap-ink hover:text-ap-primary"
          aria-expanded={open}
        >
          <span className="text-ap-muted">{open ? "▾" : "▸"}</span>
          <span className="font-medium">{t("log.list.grouped.header")}</span>
        </button>
        <span className="rounded-full bg-ap-line/50 px-2 py-0.5 text-[11px] text-ap-muted">
          {t("log.list.grouped.memberCount", { count: rows.length })}
        </span>
        <LocationChip obs={lead} />
        <span className="ms-auto text-[11px] text-ap-muted">
          {formatDistanceToNow(parseISO(lead.time), { addSuffix: true, locale: dateLocale })}
        </span>
        {canDelete ? <DeleteButton onClick={onDelete} /> : null}
      </div>
      {open ? (
        <ul className="mt-1 ms-5 flex flex-col gap-0.5 border-s border-ap-line ps-3">
          {rows.map((r) => (
            <li key={r.id} className="flex items-center gap-2 text-xs">
              <span className="text-ap-muted">{defName.get(r.signal_definition_id) ?? r.signal_code}</span>
              <span className="font-medium text-ap-ink">{formatValue(r)}</span>
              {r.notes ? <span className="text-ap-muted">— {r.notes}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function LocationChip({ obs }: { obs: SignalObservation }): ReactNode {
  const { t } = useTranslation("signals");
  if (!obs.location_mode || obs.location_mode === "entity") return null;
  return (
    <span
      className="text-[11px] text-ap-muted"
      title={
        t(`log.form.location.mode.${obs.location_mode}`) +
        (obs.location_point
          ? ` · ${obs.location_point.latitude.toFixed(5)}, ${obs.location_point.longitude.toFixed(5)}`
          : "")
      }
      aria-label={t(`log.form.location.mode.${obs.location_mode}`)}
    >
      📍
    </span>
  );
}

function DeleteButton({ onClick }: { onClick: () => void }): ReactNode {
  const { t } = useTranslation("signals");
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={t("log.list.delete.button")}
      title={t("log.list.delete.button")}
      className="text-[11px] text-ap-muted hover:text-ap-crit"
    >
      🗑
    </button>
  );
}

function DeleteConfirm({
  count,
  pending,
  onCancel,
  onConfirm,
}: {
  count: number;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}): ReactNode {
  const { t } = useTranslation("signals");
  return (
    <Modal
      open
      onClose={onCancel}
      labelledBy="obs-delete-title"
      blockEscape={pending}
      className="max-w-sm p-4"
    >
      <h3 id="obs-delete-title" className="text-sm font-semibold text-ap-ink">
        {t("log.list.delete.confirmTitle")}
      </h3>
      <p className="mt-1 text-xs text-ap-muted">
        {t("log.list.delete.confirmBody", { count })}
      </p>
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          className="rounded-md border border-ap-line bg-white px-3 py-1.5 text-xs font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
        >
          {t("log.list.delete.cancel")}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={pending}
          className="rounded-md bg-ap-crit px-3 py-1.5 text-xs font-medium text-white hover:bg-ap-crit/90 disabled:opacity-60"
        >
          {pending ? t("log.list.delete.deleting") : t("log.list.delete.confirm")}
        </button>
      </div>
    </Modal>
  );
}
