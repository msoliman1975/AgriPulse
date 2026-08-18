import { formatDistanceToNow, parseISO } from "date-fns";
import type { Locale } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActionItem } from "@/api/actionCenter";
import { Button } from "@/components/Button";
import { LinkButton } from "@/components/LinkButton";
import { Pill } from "@/components/Pill";
import { GroupMembers } from "@/modules/actionCenter/components/GroupMembers";
import {
  cellOrdinal,
  confidencePercent,
  formatCoords,
  itemDetail,
  itemTitle,
  mapsUrl,
} from "@/modules/actionCenter/lib/format";

const SEV_RAIL: Record<string, string> = {
  info: "bg-ap-line",
  warning: "bg-ap-warn",
  critical: "bg-ap-crit",
};
const SEV_PILL: Record<string, "info" | "warn" | "crit"> = {
  info: "info",
  warning: "warn",
  critical: "crit",
};
// Recurrence is loud but never red-for-agronomy: `persistent` means nobody has
// acted for days, which is a queue problem, not a worse diagnosis. Keeping it
// off the severity palette is why it uses `warn` rather than `crit`.
const RECURRENCE_PILL: Record<string, "warn" | "crit"> = {
  recurring: "warn",
  persistent: "crit",
};
// A spreading finding is worse news than a steady one and better news than
// nothing — but it is still not a severity, so it borrows the recurrence
// palette rather than the severity rail. `receding` is genuinely good news and
// is the only place a green pill appears on this row.
const TREND_PILL: Record<string, "info" | "warn" | "ok"> = {
  unknown: "info",
  steady: "info",
  spreading: "warn",
  receding: "ok",
};

interface Props {
  item: ActionItem;
  isAr: boolean;
  dateLocale: Locale;
  selected: boolean;
  expanded: boolean;
  canDispatch: boolean;
  onToggleSelect: () => void;
  onToggleExpand: () => void;
  onDispatch: () => void;
}

export function ItemRow({
  item,
  isAr,
  dateLocale,
  selected,
  expanded,
  canDispatch,
  onToggleSelect,
  onToggleExpand,
  onDispatch,
}: Props): ReactNode {
  const { t } = useTranslation("actionCenter");
  const terminal = item.status === "done" || item.status === "dismissed";
  const coords = item.cell === null ? null : formatCoords(item.cell);
  const href = item.cell === null ? null : mapsUrl(item.cell);
  const confidence = confidencePercent(item.confidence);
  const ordinal = item.cell === null ? null : cellOrdinal(item.cell);
  const detail = itemDetail(item, isAr);
  const { is_group: isGroup, member_count: memberCount, trend } = item.aggregation;
  const recurrence = item.recurrence;
  // "12 zones" alone cannot say whether this is getting worse. When there is a
  // baseline to compare against, the pill carries the direction and the number
  // it moved from; when there is not, it stays a plain count rather than
  // implying a stability nobody has measured.
  const zonesKey =
    trend === "spreading"
      ? "aggregate.zonesSpreading"
      : trend === "receding"
        ? "aggregate.zonesReceding"
        : "aggregate.zones";

  const ago = (iso: string): string =>
    formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: dateLocale });

  return (
    <div className={`flex gap-0 ${selected ? "bg-ap-bg/60" : ""}`}>
      <div className={`w-1 flex-none ${SEV_RAIL[item.severity] ?? "bg-ap-line"}`} />
      <div className="flex-none pl-3 pt-4">
        <input
          type="checkbox"
          aria-label={t("row.select")}
          checked={selected}
          disabled={terminal || !canDispatch}
          onChange={onToggleSelect}
        />
      </div>

      <div className="min-w-0 flex-1 px-3 py-3">
        <div className="flex flex-wrap items-start gap-2">
          <Pill kind={item.kind === "recommendation" ? "ok" : "crit"}>
            {t(`kind.${item.kind}`)}
          </Pill>
          <span className="text-card-title font-semibold">{itemTitle(item, isAr)}</span>
          <Pill kind={SEV_PILL[item.severity] ?? "neutral"}>{t(`severity.${item.severity}`)}</Pill>
          {/* What makes this row different from a single finding: it stands for
              N cells that all hit the same leaf at the same severity. Shown
              next to the severity because the two are read together. */}
          {isGroup ? (
            <Pill kind={TREND_PILL[trend] ?? "info"}>
              {t(zonesKey, {
                count: memberCount,
                previous: item.aggregation.previous_member_count,
              })}
            </Pill>
          ) : null}
          {recurrence.state === "new" ? null : (
            <Pill kind={RECURRENCE_PILL[recurrence.state] ?? "warn"}>
              {t(`recurrence.${recurrence.state}`, { count: recurrence.day_streak })}
            </Pill>
          )}
          <Pill kind="neutral">
            {item.action_type === null
              ? t("action.unclassified")
              : t(`action.${item.action_type}`, { defaultValue: item.action_type })}
          </Pill>
          <Pill kind="neutral">{item.native_status}</Pill>
        </div>

        {/* Location. A cell-scoped item leads with its centroid — the zone
            code it used to show is an index into a grid config and means
            nothing to someone standing in the field. */}
        <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
          {isGroup ? (
            // A group has no single coordinate to lead with, so it leads with
            // its extent instead. "Whole block" would be a lie — the finding is
            // in some of the block's cells, not all of it.
            <span className="text-ap-muted">
              {t("aggregate.acrossBlock", { count: memberCount, block: item.block_code })}
            </span>
          ) : coords === null ? (
            <span className="text-ap-muted">{t("row.wholeBlock", { block: item.block_code })}</span>
          ) : (
            <>
              <code className="rounded border border-ap-line bg-ap-bg px-1.5 py-0.5 font-mono">
                {coords}
              </code>
              <button
                type="button"
                className="text-ap-accent hover:underline"
                onClick={() => void navigator.clipboard?.writeText(coords)}
              >
                {t("row.copy")}
              </button>
              {href === null ? null : (
                <a
                  className="text-ap-accent hover:underline"
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("row.navigate")}
                </a>
              )}
              <span className="text-ap-muted">
                · {item.block_code}
                {ordinal === null ? "" : ` · ${t("row.cell", { cellNo: ordinal })}`}
              </span>
            </>
          )}
        </div>

        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-meta text-ap-muted">
          {item.tree_code === null ? null : (
            <span className="font-mono">
              {item.tree_code}
              {item.tree_version === null ? "" : `·v${item.tree_version}`}
            </span>
          )}
          <span>·</span>
          <span>{t("row.raised", { when: ago(recurrence.first_seen_at ?? item.created_at) })}</span>
          {recurrence.occurrence_count > 1 && recurrence.last_seen_at !== null ? (
            <>
              <span>·</span>
              {/* "Raised 6 days ago" alone reads as stale. It is not stale — it
                  fired again this morning, and that is the fact that decides
                  whether it still needs doing. */}
              <span>{t("row.lastSeen", { when: ago(recurrence.last_seen_at) })}</span>
            </>
          ) : null}
          <span>·</span>
          <span
            className={
              item.due_bucket === "overdue"
                ? "font-semibold text-ap-crit"
                : item.due_bucket === "today"
                  ? "font-semibold text-ap-warn"
                  : ""
            }
          >
            {t(`due.${item.due_bucket}`)}
          </span>
          {item.scheduled_date === null ? null : (
            <>
              <span>·</span>
              <span>{t("row.scheduled", { date: item.scheduled_date })}</span>
            </>
          )}
        </div>

        {expanded ? (
          <div className="mt-2.5 rounded-lg border border-ap-line bg-ap-bg/60 p-3">
            <h4 className="mb-1.5 text-meta font-bold uppercase tracking-wide text-ap-muted">
              {t("why.title")}
            </h4>
            <p className="text-sm">{item.why ?? t("why.none")}</p>
            {detail === null ? null : <p className="mt-1.5 text-sm text-ap-muted">{detail}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2 text-meta text-ap-muted">
              {item.kind === "alert" ? (
                <span>{t("why.alertCertainty")}</span>
              ) : confidence === null ? null : (
                <span>{t("why.confidence", { percent: confidence })}</span>
              )}
              {recurrence.occurrence_count > 1 ? (
                <span>
                  ·{" "}
                  {t("recurrence.summary", {
                    days: recurrence.occurrence_count,
                    streak: recurrence.day_streak,
                  })}
                </span>
              ) : null}
            </div>
            {isGroup ? (
              <GroupMembers
                farmId={item.farm_id}
                itemId={item.id}
                isAr={isAr}
                previousCount={item.aggregation.previous_member_count}
              />
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="flex flex-none flex-col items-end gap-1.5 px-3 py-3">
        <div className="flex gap-1">
          {/* Only once there is an activity to open. A board link on an
              undispatched item points at nothing in particular. */}
          {item.activity_id === null ? null : (
            <LinkButton
              size="sm"
              variant="ghost"
              to={`/board/${item.farm_id}?activity=${item.activity_id}&lane=${item.block_id}`}
            >
              {t("actions.openOnBoard")}
            </LinkButton>
          )}
          <Button size="sm" variant="ghost" onClick={onToggleExpand}>
            {expanded ? t("actions.hideWhy") : t("actions.why")}
          </Button>
          {terminal || !canDispatch ? null : (
            <Button size="sm" onClick={onDispatch}>
              {t("actions.dispatch")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
