import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useSearchParams } from "react-router-dom";

import type {
  ActionItem,
  DateRange,
  GroupBy,
  ItemKind,
  ItemSeverity,
  NativeStatus,
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
import { isApiError } from "@/api/errors";
import { useActionItems, useCloseActionItem } from "@/queries/actionCenter";
import { useTenantUsers } from "@/queries/users";
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

// The row's own states, grouped by kind so the picker reads as two lists
// rather than eight loose words. Four of them share the `dismissed` tab, which
// is why this filter exists at all.
const NATIVE_STATUSES: ReadonlyArray<{ kind: ItemKind; values: readonly NativeStatus[] }> = [
  { kind: "recommendation", values: ["open", "applied", "deferred", "dismissed", "expired"] },
  { kind: "alert", values: ["open", "acknowledged", "resolved", "snoozed"] },
];

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
  // Four separate permissions, because closing an item is not dispatching it.
  // An Agronomist holds the three closing ones and holds no `plan.manage`.
  const canAcknowledge = useCapability("alert.acknowledge", { farmId });
  const canResolve = useCapability("alert.resolve", { farmId });
  const canAct = useCapability("recommendation.act", { farmId });

  // `?kind=alert` narrows the queue on arrival. The Insights alert card and
  // the two KPI tiles used to open single-kind screens; landing on a mixed
  // queue after clicking a tile that counted one kind reads as a wrong number.
  // Read once, as the initial value — after that the toolbar owns the filter.
  const [search] = useSearchParams();
  const [tab, setTab] = useState<UnifiedStatus | "all">("needs_action");
  const [groupBy, setGroupBy] = useState<GroupBy>("action_type");
  const [kinds, setKinds] = useState<Set<ItemKind>>(() => {
    const requested = search.get("kind");
    return requested === "alert" || requested === "recommendation"
      ? new Set<ItemKind>([requested])
      : new Set<ItemKind>(["recommendation", "alert"]);
  });
  const [range, setRange] = useState<DateRange>("30d");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [severity, setSeverity] = useState<ItemSeverity | "">("");
  const [nativeStatus, setNativeStatus] = useState<NativeStatus | "">("");
  const [blockId, setBlockId] = useState("");
  const [assignee, setAssignee] = useState("");

  // Groups start COLLAPSED, so the screen opens as a summary of what needs
  // doing rather than a wall of rows. We track what the user has *opened*
  // rather than what they closed: a group that appears after a filter change
  // then starts collapsed like the rest, instead of springing open.
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set());
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
      ...(nativeStatus !== "" ? { native_status: [nativeStatus] } : {}),
      ...(blockId !== "" ? { block_id: blockId } : {}),
      ...(assignee !== "" ? { assigned_membership_id: assignee } : {}),
      ...(range === "custom"
        ? {
            ...(customFrom !== "" ? { raised_from: new Date(customFrom).toISOString() } : {}),
            ...(customTo !== ""
              ? { raised_to: new Date(`${customTo}T23:59:59`).toISOString() }
              : {}),
          }
        : { date_range: range }),
    };
  }, [
    farmId,
    tab,
    kinds,
    groupBy,
    severity,
    nativeStatus,
    blockId,
    assignee,
    range,
    customFrom,
    customTo,
  ]);

  const query = useActionItems(params);
  const tenantUsers = useTenantUsers();
  const close = useCloseActionItem();

  // A notification links to one row: `?item=<id>`. Groups start collapsed, so
  // without this the link lands on a screen where the row it names is not on
  // the page at all. Runs once per id — after that the user owns what is open,
  // and re-opening a group they just closed would be a fight.
  const deepLinked = search.get("item");
  const revealed = useRef<string | null>(null);
  useEffect(() => {
    if (deepLinked === null || revealed.current === deepLinked) return;
    const holder = (query.data?.groups ?? []).find((g) => g.items.some((i) => i.id === deepLinked));
    if (holder === undefined) return;
    revealed.current = deepLinked;
    setExpandedGroups((prev) => new Set(prev).add(holder.key));
    setExpanded((prev) => new Set(prev).add(deepLinked));
  }, [deepLinked, query.data]);

  if (farmId === undefined) {
    return <Navigate to="/" replace />;
  }

  const data = query.data;
  const groups = data?.groups ?? [];
  const counts = data?.status_counts ?? {};
  const allItems = groups.flatMap((g) => g.items);
  const blockCodes = [...new Set(allItems.map((i) => i.block_code))].sort();

  // People who hold work in the current result set. Derived from the items so
  // the filter can never offer a name that would return nothing.
  const userByMembership = new Map((tenantUsers.data ?? []).map((u) => [u.membership_id, u]));
  const assignees = [
    ...new Set(
      allItems.map((i) => i.assigned_membership_id).filter((id): id is string => id !== null),
    ),
  ]
    .map((id) => ({ id, name: userByMembership.get(id)?.full_name ?? id.slice(0, 8) }))
    .sort((a, b) => a.name.localeCompare(b.name));

  const anyFilterActive =
    severity !== "" ||
    nativeStatus !== "" ||
    blockId !== "" ||
    assignee !== "" ||
    range !== "30d" ||
    kinds.size !== 2 ||
    customFrom !== "" ||
    customTo !== "";

  const clearFilters = (): void => {
    setSeverity("");
    setNativeStatus("");
    setBlockId("");
    setAssignee("");
    setRange("30d");
    setCustomFrom("");
    setCustomTo("");
    setKinds(new Set<ItemKind>(["recommendation", "alert"]));
  };

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
    setExpandedGroups((prev) => {
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

          {/* The row's own state. The tabs cannot reach four of these:
              `deferred`, `expired`, `snoozed` and `dismissed` all sit in one
              tab, so without this there is no way to list just the deferred
              ones. */}
          <select
            className="input w-auto"
            aria-label={t("filters.nativeStatus")}
            value={nativeStatus}
            onChange={(e) => setNativeStatus(e.target.value as NativeStatus | "")}
          >
            <option value="">{t("filters.anyState")}</option>
            {NATIVE_STATUSES.filter((group) => kinds.has(group.kind)).map((group) => (
              <optgroup key={group.kind} label={t(`kind.${group.kind}`)}>
                {group.values.map((value) => (
                  <option key={`${group.kind}:${value}`} value={value}>
                    {t(`nativeStatus.${value}`)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>

          {/* Assigned-to. Only meaningful once something has been dispatched,
              so the options are the people who actually hold work here rather
              than the whole roster. */}
          <select
            className="input w-auto"
            aria-label={t("filters.assignedTo")}
            value={assignee}
            onChange={(e) => setAssignee(e.target.value)}
          >
            <option value="">{t("filters.anyone")}</option>
            {assignees.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>

          {anyFilterActive ? (
            <Button size="sm" variant="ghost" onClick={clearFilters}>
              {t("filters.clearAll")}
            </Button>
          ) : null}

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
          const shut = !expandedGroups.has(group.key);
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
                  {/* Rows vs cells: `count` is what is on screen, `cell_count`
                      is what is in the field. They diverge as soon as anything
                      aggregates, and the header has to say both or it looks
                      like the farm got quieter. */}
                  {group.aggregate_count > 0
                    ? ` · ${t("group.aggregated", { count: group.aggregate_count })}`
                    : ""}
                  {group.recurring_count > 0
                    ? ` · ${t("group.recurring", { count: group.recurring_count })}`
                    : ""}
                  {group.spreading_count > 0
                    ? ` · ${t("group.spreading", { count: group.spreading_count })}`
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
                      canAcknowledge={canAcknowledge}
                      canResolve={canResolve}
                      canAct={canAct}
                      closing={close.isPending}
                      onClose={(payload) =>
                        close.mutate(
                          item.kind === "alert"
                            ? { kind: "alert", id: item.id, payload }
                            : { kind: "recommendation", id: item.id, payload },
                        )
                      }
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

      {/* A failed close is silent otherwise: the row simply does not move, and
          the user presses the button again. The server's own `detail` is
          shown, because "could not close" hides which rule refused — acting on
          a member of a group returns a 409 that says exactly that. */}
      {close.isError ? (
        <div
          role="alert"
          className="mb-3 rounded-card border border-ap-crit-soft bg-ap-crit-soft/40 p-3 text-sm text-ap-crit"
        >
          {t("close.failed")}
          {apiDetail(close.error) === null ? "" : ` — ${apiDetail(close.error)}`}
        </div>
      ) : null}

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

/** The server's own explanation, when it sent one. */
function apiDetail(error: unknown): string | null {
  if (!isApiError(error)) return null;
  return error.problem.detail ?? error.problem.title ?? null;
}

export default ActionCenterPage;
