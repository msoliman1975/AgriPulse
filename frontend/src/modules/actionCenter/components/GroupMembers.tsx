import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActionItemMember } from "@/api/actionCenter";
import { Pill } from "@/components/Pill";
import { useActionItemMembers } from "@/queries/actionCenter";
import { formatCoords, mapsUrl } from "@/modules/actionCenter/lib/format";

interface Props {
  farmId: string;
  itemId: string;
  isAr: boolean;
  /** Yesterday's member count, so the panel header can state the baseline the
   *  card's arrow is drawn against. 0 when there is no yesterday. */
  previousCount: number;
}

function memberText(member: ActionItemMember, isAr: boolean): string | null {
  return isAr ? (member.text_ar ?? member.text_en) : member.text_en;
}

/**
 * The cells behind one aggregated card.
 *
 * Rendered only while the row is expanded, and fetched then too — a farm-wide
 * queue can hold hundreds of groups, and loading every membership up front
 * would swap the request-per-row this feature removes for a different one.
 *
 * Cells that have stopped firing are listed, greyed, after the live ones
 * rather than hidden. A shrinking outbreak is a different situation from one
 * that never spread, and dropping the quiet cells makes the two look identical.
 */
export function GroupMembers({ farmId, itemId, isAr, previousCount }: Props): ReactNode {
  const { t } = useTranslation("actionCenter");
  const query = useActionItemMembers(farmId, itemId);

  if (query.isPending) {
    return <p className="mt-2 text-meta text-ap-muted">{t("members.loading")}</p>;
  }
  if (query.isError || query.data === undefined) {
    return <p className="mt-2 text-meta text-ap-crit">{t("members.failed")}</p>;
  }

  const { members, active, total } = query.data;
  if (total === 0) {
    return <p className="mt-2 text-meta text-ap-muted">{t("members.none")}</p>;
  }

  return (
    <div className="mt-2.5">
      <h4 className="mb-1.5 text-meta font-bold uppercase tracking-wide text-ap-muted">
        {previousCount > 0 && previousCount !== active
          ? t("members.spreadTitle", { active, total, previous: previousCount })
          : t("members.title", { active, total })}
      </h4>
      <ul className="flex flex-col gap-1">
        {members.map((member) => {
          const coords = member.cell === null ? null : formatCoords(member.cell);
          const href = member.cell === null ? null : mapsUrl(member.cell);
          const cleared = member.cleared_at !== null;
          const detail = memberText(member, isAr);
          return (
            <li
              key={member.id}
              className={`flex flex-wrap items-center gap-2 text-xs ${
                cleared ? "text-ap-muted line-through decoration-ap-line" : ""
              }`}
            >
              <span className="font-medium">
                {member.cell === null
                  ? t("members.unlocated")
                  : t("members.cellAt", {
                      row: member.cell.row,
                      col: member.cell.col,
                    })}
              </span>
              {coords === null ? null : (
                <code className="rounded border border-ap-line bg-ap-bg px-1.5 py-0.5 font-mono">
                  {coords}
                </code>
              )}
              {href === null || cleared ? null : (
                <a
                  className="text-ap-accent hover:underline"
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("row.navigate")}
                </a>
              )}
              {member.day_streak > 1 ? (
                <span>· {t("members.days", { count: member.day_streak })}</span>
              ) : null}
              {cleared ? <Pill kind="neutral">{t("members.cleared")}</Pill> : null}
              {detail === null || detail.length === 0 ? null : (
                <span className="text-ap-muted">· {detail}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
