import { formatDistanceToNow, parseISO } from "date-fns";
import type { Locale } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActionItem } from "@/api/actionCenter";
import { Button } from "@/components/Button";
import { LinkButton } from "@/components/LinkButton";
import { Pill } from "@/components/Pill";
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
          {coords === null ? (
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
          <span>{t("row.raised", { when: ago(item.created_at) })}</span>
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
            </div>
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
