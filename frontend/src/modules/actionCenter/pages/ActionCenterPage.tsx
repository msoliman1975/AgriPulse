import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import type {
  ActionItem,
  DateRange,
  GroupBy,
  ItemKind,
  ItemSeverity,
  UnifiedStatus,
} from "@/api/actionCenter";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { DispatchDialog } from "@/modules/actionCenter/components/DispatchDialog";
import { ItemRow } from "@/modules/actionCenter/components/ItemRow";
import { useActionItems } from "@/queries/actionCenter";
import { useCapability } from "@/rbac/useCapability";

const TABS: ReadonlyArray<UnifiedStatus | "all"> = [
  "needs_action",
  "dispatched",
  "done",
  "dismissed",
  "all",
];

const GROUPS: ReadonlyArray<GroupBy> = ["action_type", "block", "due", "none"];

const RANGES: ReadonlyArray<DateRange> = ["1d", "7d", "30d", "90d", "all", "custom"];

const SEVERITIES: ReadonlyArray<ItemSeverity> = ["critical", "warning", "info"];

/**
 * Action Center — one queue over recommendations and alerts.
 *
 * Replaces nothing yet: /recommendations and /alerts stay routed until this
 * screen is signed off.
 */
export function ActionCenterPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t, i18n } = useTranslation("actionCenter");
  const dateLocale = useDateLocale();
  const isAr = i18n.language === "ar";
  const canDispatch = useCapability("plan.manage", { farmId });

  const [tab, setTab] = useState<UnifiedStatus | "all">("needs_action");
  const [groupBy, setGroupBy] = useState<GroupBy>("action_type");
  const [kinds, setKinds] = useState<Set<ItemKind>>(
    () => new Set<ItemKind>(["recommendation", "alert"]),
  );
  const [range, setRange] = useState<DateRange>("30d");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [severity, setSeverity] = useState<ItemSeverity | "">("");
  const [blockId, setBlockId] = useState("");

  // Collapse state is keyed by group key and deliberately survives tab and
  // filter changes — a supervisor who shut "Monitoring" wants it to stay shut.
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [dispatching, setDispatching] = useState<ActionItem[] | null>(null);

  const params = useMemo(() => {
    if (farmId === undefined) return null;
    return {
      farm_id: farmId,
      status: tab,
      kind: [...kinds],
      group_by: groupBy,
      ...(severity !== "" ? { severity: [severity] } : {}),
      ...(blockId !== "" ? { block_id: blockId } : {}),
      ...(range === "custom"
        ? {
            ...(customFrom !== "" ? { raised_from: new Date(customFrom).toISOString() } : {}),
            ...(customTo !== ""
              ? { raised_to: new Date(`${customTo}T23:59:59`).toISOString() }
              : {}),
          }
        : { date_range: range }),
    };
  }, [farmId, tab, kinds, groupBy, severity, blockId, range, customFrom, customTo]);

  const query = useActionItems(params);

  if (farmId === undefined) {
    return <Navigate to="/" replace />;
  }

  const data = query.data;
  const groups = data?.groups ?? [];
  const counts = data?.status_counts ?? {};
  const allItems = groups.flatMap((g) => g.items);
  const blockCodes = [...new Set(allItems.map((i) => i.block_code))].sort();

  const toggleKind = (kind: ItemKind): void => {
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      // Never allow an empty type filter — it reads as "nothing matched" when
      // it actually means "you asked for nothing".
      return next.size === 0 ? prev : next;
    });
  };

  const toggleGroup = (key: string): void =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const toggleSelect = (id: string): void =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const selectedItems = allItems.filter((i) => selected.has(i.id));

  return (
    <Page>
      <PageHeader
        title={t("page.title")}
        subtitle={t("page.subtitle")}
        actions={
          <>
            <SegmentedControl
              ariaLabel={t("tabsLabel")}
              items={TABS.map((v) => ({
                value: v,
                label:
                  v === "all"
                    ? t("tabs.all")
                    : `${t(`tabs.${v}`)}${counts[v] === undefined ? "" : ` (${counts[v]})`}`,
              }))}
              value={tab}
              onChange={(v) => setTab(v)}
            />
          </>
        }
      />

      {/* ---- toolbar ---- */}
      <Card className="mb-4 flex flex-col gap-3 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
            {t("filters.type")}
          </span>
          <Button
            size="sm"
            variant={kinds.size === 2 ? "primary" : "secondary"}
            onClick={() =>
              setKinds(
                kinds.size === 2
                  ? new Set<ItemKind>(["recommendation"])
                  : new Set<ItemKind>(["recommendation", "alert"]),
              )
            }
          >
            {t("filters.selectAll")}
          </Button>
          {(["recommendation", "alert"] as const).map((k) => (
            <Button
              key={k}
              size="sm"
              variant={kinds.has(k) ? "primary" : "secondary"}
              aria-pressed={kinds.has(k)}
              onClick={() => toggleKind(k)}
            >
              {t(`kind.${k}`)}
            </Button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
            {t("filters.raised")}
          </span>
          <select
            className="input w-auto"
            aria-label={t("filters.raised")}
            value={range}
            onChange={(e) => setRange(e.target.value as DateRange)}
          >
            {RANGES.map((r) => (
              <option key={r} value={r}>
                {t(`ranges.${r}`)}
              </option>
            ))}
          </select>
          {range === "custom" ? (
            <>
              <input
                type="date"
                className="input w-auto"
                aria-label={t("filters.from")}
                value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
              />
              <span className="text-xs text-ap-muted">{t("filters.to")}</span>
              <input
                type="date"
                className="input w-auto"
                aria-label={t("filters.to")}
                value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
              />
            </>
          ) : null}

          <select
            className="input w-auto"
            aria-label={t("filters.block")}
            value={blockId}
            onChange={(e) => setBlockId(e.target.value)}
          >
            <option value="">{t("filters.allBlocks")}</option>
            {blockCodes.map((code) => {
              const match = allItems.find((i) => i.block_code === code);
              return (
                <option key={code} value={match?.block_id ?? ""}>
                  {code}
                </option>
              );
            })}
          </select>

          <select
            className="input w-auto"
            aria-label={t("filters.severity")}
            value={severity}
            onChange={(e) => setSeverity(e.target.value as ItemSeverity | "")}
          >
            <option value="">{t("filters.allSeverities")}</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {t(`severity.${s}`)}
              </option>
            ))}
          </select>

          <div className="flex-1" />
          <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
            {t("filters.groupBy")}
          </span>
          <SegmentedControl
            ariaLabel={t("filters.groupBy")}
            items={GROUPS.map((g) => ({ value: g, label: t(`groupBy.${g}`) }))}
            value={groupBy}
            onChange={(v) => setGroupBy(v)}
          />
        </div>
      </Card>

      {/* ---- list ---- */}
      {query.isPending ? (
        <Card className="p-8 text-center text-ap-muted">{t("page.loading")}</Card>
      ) : query.isError ? (
        <div className="rounded-card border border-ap-crit-soft bg-ap-crit-soft/40 p-6 text-center text-ap-crit">
          {t("page.loadFailed")}
        </div>
      ) : groups.length === 0 ? (
        <EmptyState message={t("page.empty")} action={null} />
      ) : (
        groups.map((group) => {
          const shut = collapsed.has(group.key);
          const selectable = group.items.filter(
            (i) => i.status !== "done" && i.status !== "dismissed",
          );
          const allSelected = selectable.length > 0 && selectable.every((i) => selected.has(i.id));
          return (
            <div key={group.key} className="mb-3">
              <div className="flex flex-wrap items-center gap-3 rounded-t-card border border-ap-line bg-ap-bg px-3 py-2">
                <button
                  type="button"
                  className="text-ap-muted"
                  aria-expanded={!shut}
                  aria-label={t(shut ? "group.expand" : "group.collapse", {
                    group: group.label,
                  })}
                  onClick={() => toggleGroup(group.key)}
                >
                  {shut ? "▸" : "▾"}
                </button>
                <input
                  type="checkbox"
                  aria-label={t("group.selectAllIn", { group: group.label })}
                  checked={allSelected}
                  disabled={selectable.length === 0 || !canDispatch}
                  onChange={(e) =>
                    setSelected((prev) => {
                      const next = new Set(prev);
                      selectable.forEach((i) =>
                        e.target.checked ? next.add(i.id) : next.delete(i.id),
                      );
                      return next;
                    })
                  }
                />
                <span className="text-card-title font-semibold">{group.label}</span>
                <span className="text-meta text-ap-muted">
                  {t("group.meta", {
                    count: group.count,
                    blocks: group.block_count,
                  })}
                  {group.cell_count > 0
                    ? ` · ${t("group.atCellLevel", { count: group.cell_count })}`
                    : ""}
                  {group.critical_count > 0
                    ? ` · ${t("group.critical", { count: group.critical_count })}`
                    : ""}
                </span>
                {groupBy === "block" ? (
                  <Pill kind={group.responsible_membership_id === null ? "warn" : "ok"}>
                    {group.responsible_membership_id === null
                      ? t("group.noResponsible")
                      : t("group.responsible")}
                  </Pill>
                ) : null}
                <div className="flex-1" />
                {canDispatch && selectable.length > 0 ? (
                  <Button size="sm" onClick={() => setDispatching(selectable)}>
                    {t("actions.dispatchAll", { count: selectable.length })}
                  </Button>
                ) : null}
              </div>
              {shut ? null : (
                <div className="divide-y divide-ap-line rounded-b-card border border-t-0 border-ap-line bg-ap-panel">
                  {group.items.map((item) => (
                    <ItemRow
                      key={item.id}
                      item={item}
                      isAr={isAr}
                      dateLocale={dateLocale}
                      selected={selected.has(item.id)}
                      expanded={expanded.has(item.id)}
                      canDispatch={canDispatch}
                      onToggleSelect={() => toggleSelect(item.id)}
                      onToggleExpand={() =>
                        setExpanded((prev) => {
                          const next = new Set(prev);
                          if (next.has(item.id)) next.delete(item.id);
                          else next.add(item.id);
                          return next;
                        })
                      }
                      onDispatch={() => setDispatching([item])}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })
      )}

      {/* ---- bulk bar ---- */}
      {selectedItems.length > 0 ? (
        <div className="fixed inset-x-0 bottom-5 z-40 mx-auto flex w-fit items-center gap-2 rounded-card bg-ap-ink px-3 py-2 text-white shadow-lg">
          <span className="px-1 text-sm font-semibold">
            {t("bulk.selected", { count: selectedItems.length })}
          </span>
          <Button size="sm" onClick={() => setDispatching(selectedItems)}>
            {t("actions.dispatchTo")}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setSelected(new Set())}>
            {t("bulk.clear")}
          </Button>
        </div>
      ) : null}

      {dispatching !== null ? (
        <DispatchDialog
          farmId={farmId}
          items={dispatching}
          onClose={() => setDispatching(null)}
          onDispatched={() => {
            setDispatching(null);
            setSelected(new Set());
          }}
        />
      ) : null}
    </Page>
  );
}

export default ActionCenterPage;
