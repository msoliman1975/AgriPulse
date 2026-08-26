import { formatDistanceToNow, parseISO } from "date-fns";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { SignalDefinition, SignalObservation } from "@/api/signals";
import { AnchoredPopup } from "@/components/AnchoredPopup";
import { useDateLocale } from "@/hooks/useDateLocale";

import { formatObservationValue } from "./signalOverlay";

interface Props {
  observation: SignalObservation | null;
  definition: SignalDefinition | null;
  isLoading: boolean;
  /**
   * Every reading on the clicked spot, newest first, when the mark stands for
   * more than one. Entity-mode observations have no coordinate of their own,
   * so a block that a scout visited four times produces four readings on one
   * point — the map can draw a single mark for them, and this is what makes
   * the other three reachable instead of buried under it.
   *
   * Empty or single means there is nothing to switch between and no row is
   * drawn.
   */
  stack?: readonly SignalObservation[];
  onSelectFromStack?: (observationId: string) => void;
  /**
   * The day the console is reading the farm as of, or null for "now".
   *
   * Only used to explain an observation that is no longer in the list. With a
   * date selected the reason is almost always that the reading was recorded
   * after that day, and the old copy — "pick the matching signal in the
   * overlay control" — sent the reader to a control that cannot help.
   */
  asOfDate?: string | null;
  // Click pixel coords (relative to the map container) — anchor the card
  // next to the clicked observation dot. Null falls back to the fixed
  // top-right corner. Mirrors GridCellPopup so the two read as siblings.
  x: number | null;
  y: number | null;
  onClose: () => void;
}

/**
 * Inline observation popup for the Labs map. Renders the full
 * SignalObservation when the user clicks a marker in the CS-8 overlay;
 * data comes from the same react-query result the overlay already loaded,
 * so no extra API round-trip. Card chrome + the descriptive title + the
 * click-anchoring all come from the shared AnchoredPopup wrapper, so this
 * looks + behaves identically to the grid-cell popup.
 */
export function SignalObservationPanel({
  observation,
  definition,
  isLoading,
  stack = [],
  onSelectFromStack,
  asOfDate = null,
  x,
  y,
  onClose,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("signals");
  const dateLocale = useDateLocale();
  // The stack row is a list of DAYS, not relative ages: four readings from
  // the same week all render as "5 days ago" and become indistinguishable.
  const stackDayFmt = useMemo(
    () => new Intl.DateTimeFormat(i18n.language, { day: "2-digit", month: "short" }),
    [i18n.language],
  );
  // A scout who visits a block twice in one morning produces two readings on
  // one day, and two chips both reading "18 Aug" name neither. The time is
  // added only where the day does not already separate them, so the common
  // case stays short.
  const stackTimeFmt = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.language, {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      }),
    [i18n.language],
  );
  const dayIsAmbiguous = useMemo(() => {
    const seen = new Map<string, number>();
    for (const o of stack) {
      const key = o.time.slice(0, 10);
      seen.set(key, (seen.get(key) ?? 0) + 1);
    }
    return seen;
  }, [stack]);

  if (isLoading) {
    return (
      <AnchoredPopup x={x} y={y} title={t("observationPanel.title")} onClose={onClose}>
        <p className="text-ap-muted">{t("observationPanel.loading")}</p>
      </AnchoredPopup>
    );
  }

  if (!observation) {
    return (
      <AnchoredPopup x={x} y={y} title={t("observationPanel.title")} onClose={onClose}>
        <p className="text-ap-crit">
          {asOfDate
            ? t("observationPanel.notInScene", { date: asOfDate })
            : t("observationPanel.notFound")}
        </p>
      </AnchoredPopup>
    );
  }

  const valueDisplay = formatObservationValue(observation);
  const observedAtIso = observation.time;
  const recordedAtIso = observation.inserted_at;
  const definitionLabel =
    definition?.name ?? observation.signal_code ?? observation.signal_definition_id;

  return (
    <AnchoredPopup
      x={x}
      y={y}
      title={t("observationPanel.title")}
      subtitle={definitionLabel}
      onClose={onClose}
    >
      <p className="mb-2 font-mono text-[10px] text-ap-muted">{observation.signal_code}</p>

      {/* Other readings on this exact spot. A row of dates rather than a
          count, because "4 readings here" tells a reader there is something
          they cannot reach; the dates are the thing they came for. */}
      {stack.length > 1 && onSelectFromStack ? (
        <div className="mb-2 border-b border-ap-line pb-2">
          <p className="mb-1 text-[10px] uppercase tracking-wide text-ap-muted">
            {t("observationPanel.stack", { count: stack.length })}
          </p>
          <div className="flex flex-wrap gap-1">
            {stack.map((o) => {
              const active = o.id === observation.id;
              return (
                <button
                  key={o.id}
                  type="button"
                  onClick={() => onSelectFromStack(o.id)}
                  title={o.signal_code}
                  className={
                    "rounded-md border px-1.5 py-0.5 text-[10px] tabular-nums " +
                    (active
                      ? "border-ap-primary bg-ap-primary-soft text-ap-primary"
                      : "border-ap-line text-ap-ink hover:bg-ap-bg")
                  }
                >
                  {(dayIsAmbiguous.get(o.time.slice(0, 10)) ?? 0) > 1
                    ? stackTimeFmt.format(parseISO(o.time))
                    : stackDayFmt.format(parseISO(o.time))}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-[11px]">
        <dt className="text-ap-muted">{t("observationPanel.value")}</dt>
        <dd className="font-mono tabular-nums text-ap-ink">
          {valueDisplay}
          {definition?.unit ? <span className="ms-1 text-ap-muted">{definition.unit}</span> : null}
        </dd>

        <dt className="text-ap-muted">{t("observationPanel.observedAt")}</dt>
        <dd className="text-ap-ink">
          {formatDistanceToNow(parseISO(observedAtIso), {
            addSuffix: true,
            locale: dateLocale,
          })}
        </dd>

        {recordedAtIso !== observedAtIso ? (
          <>
            <dt className="text-ap-muted">{t("observationPanel.recordedAt")}</dt>
            <dd className="text-ap-ink">
              {formatDistanceToNow(parseISO(recordedAtIso), {
                addSuffix: true,
                locale: dateLocale,
              })}
            </dd>
          </>
        ) : null}

        <dt className="text-ap-muted">{t("observationPanel.locationMode")}</dt>
        <dd className="text-ap-ink">
          {t(`observationPanel.locationModes.${observation.location_mode ?? "entity"}`)}
        </dd>

        {observation.location_point ? (
          <>
            <dt className="text-ap-muted">{t("observationPanel.locationPoint")}</dt>
            <dd className="font-mono text-[10px] text-ap-ink">
              {observation.location_point.latitude.toFixed(5)},{" "}
              {observation.location_point.longitude.toFixed(5)}
            </dd>
          </>
        ) : null}

        {observation.block_id ? (
          <>
            <dt className="text-ap-muted">{t("observationPanel.block")}</dt>
            <dd className="font-mono text-[10px] text-ap-ink">
              {observation.block_id.slice(0, 8)}…
            </dd>
          </>
        ) : null}

        {observation.template_observation_id ? (
          <>
            <dt className="text-ap-muted">{t("observationPanel.template")}</dt>
            <dd className="text-[10px] text-ap-muted">
              {observation.template_observation_id === observation.id
                ? t("observationPanel.templateLead")
                : t("observationPanel.templateSibling")}
            </dd>
          </>
        ) : null}
      </dl>

      {observation.notes ? (
        <p className="mt-2 border-t border-ap-line pt-2 text-[11px] italic text-ap-muted">
          {observation.notes}
        </p>
      ) : null}

      {observation.attachment_download_url ? (
        <a
          href={observation.attachment_download_url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-[10px] text-ap-primary underline"
        >
          {t("observationPanel.attachment")}
        </a>
      ) : null}
    </AnchoredPopup>
  );
}
