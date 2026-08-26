// What happened, for the day the play head is parked on.
//
// The rail follows the same fade rule as the map: today's events at full
// strength, the last few days dimmed and labelled with their age, then
// gone. Two lists would let the map and the rail disagree about what is
// "on screen", which is the one thing a replay cannot afford.

import { useEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TimelineEvent, TimelineEventKind } from "@/api/timeline";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Pill";
import { markerSeverity } from "@/modules/labs/map/markerIcons";
import { daysBetween, type FadedEvent } from "../lib/frames";

interface Props {
  frameDay: string | null;
  visible: readonly FadedEvent[];
  /** Kinds the caller has no capability for. Named, never silently empty. */
  omittedKinds: readonly TimelineEventKind[];
  truncated: boolean;
  /** Set by a click on the map; the matching row scrolls into view. */
  focusedEventId: string | null;
  onFocusEvent: (eventId: string | null) => void;
  formatDay: (day: string) => string;
  formatTime: (iso: string) => string;
}

/** Severity to the `<Pill>` kind. `Pill` carries ok / warn / crit. */
function pillKind(event: TimelineEvent): "ok" | "warn" | "crit" {
  switch (markerSeverity(event.severity)) {
    case "critical":
      return "crit";
    case "watch":
      return "warn";
    default:
      return "ok";
  }
}

export function EventRail({
  frameDay,
  visible,
  omittedKinds,
  truncated,
  focusedEventId,
  onFocusEvent,
  formatDay,
  formatTime,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("timeline");
  const focusedRef = useRef<HTMLLIElement | null>(null);

  useEffect(() => {
    focusedRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focusedEventId]);

  // Freshest first here, which is the opposite of the map's draw order —
  // the map wants the newest painted last so it wins a collision; a reader
  // wants it at the top.
  const rows = [...visible].sort(
    (a, b) => b.opacity - a.opacity || b.event.at.localeCompare(a.event.at),
  );

  const title = (event: TimelineEvent): string => {
    const own = i18n.language.startsWith("ar")
      ? (event.title_ar ?? event.title_en)
      : event.title_en;
    if (own) return own;
    // No text on the row. The enum-ish code is the next best thing, and
    // the kind's own label is the floor — never an empty line, which reads
    // as a rendering bug rather than as a datapoint with no note.
    if (event.code) {
      return t(`code.${event.kind}.${event.code}`, { defaultValue: event.code });
    }
    return t(`kind.${event.kind}`);
  };

  return (
    <Card
      className="flex h-full min-h-0 flex-col"
      noPadding
      // `bodyClassName` is what makes the rail scroll instead of growing.
      //
      // A Card WITH a title wraps its children in a plain <div>. That div is
      // a flex child of the Card but is not itself a flex container, so the
      // `flex-1 min-h-0 overflow-y-auto` below had a non-flex parent: its
      // `flex-1` did nothing, its height resolved to content, and
      // `overflow-y-auto` never had a bounded box to scroll inside.
      //
      // On a quiet day that is invisible — seven rows fit. On 5 August this
      // farm has 108 alerts, and the rail grew to 108 rows tall, took the
      // page with it, and pushed the scrubber and its play button far below
      // the fold. The screen that opened was one you had to scroll to use.
      bodyClassName="flex min-h-0 flex-1 flex-col"
      title={frameDay ? t("rail.title", { date: formatDay(frameDay) }) : t("rail.titleNoDay")}
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 ? (
          <div className="p-4">
            <EmptyState message={t("rail.empty")} />
          </div>
        ) : (
          <ul className="divide-y divide-ap-line">
            {rows.map(({ event, opacity }) => {
              const age = frameDay ? daysBetween(event.day, frameDay) : 0;
              const focused = focusedEventId === event.id;
              return (
                <li
                  key={`${event.kind}:${event.id}`}
                  ref={focused ? focusedRef : undefined}
                  // Opacity carries the age, exactly as it does on the map,
                  // so a row and its mark dim together.
                  style={{ opacity: 0.45 + opacity * 0.55 }}
                  className={focused ? "bg-ap-primary-soft" : undefined}
                >
                  <button
                    type="button"
                    onClick={() => onFocusEvent(focused ? null : event.id)}
                    className="w-full px-4 py-2.5 text-start hover:bg-ap-bg"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Pill kind={pillKind(event)}>{t(`kind.${event.kind}`)}</Pill>
                      {event.block_code ? (
                        <span className="text-meta text-ap-muted">
                          {event.block_name ?? event.block_code}
                        </span>
                      ) : null}
                      <span className="ms-auto text-meta text-ap-muted">
                        {age === 0 ? formatTime(event.at) : t("rail.daysAgo", { count: age })}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-ap-ink">{title(event)}</p>
                    {event.detail ? (
                      <p className="mt-0.5 text-meta text-ap-muted">{event.detail}</p>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {omittedKinds.length > 0 || truncated ? (
        <div className="border-t border-ap-line px-4 py-2 text-meta text-ap-muted">
          {omittedKinds.length > 0 ? (
            <p>
              {t("rail.omitted", {
                kinds: omittedKinds.map((k) => t(`kind.${k}`)).join(", "),
              })}
            </p>
          ) : null}
          {truncated ? <p>{t("rail.truncated")}</p> : null}
        </div>
      ) : null}
    </Card>
  );
}
