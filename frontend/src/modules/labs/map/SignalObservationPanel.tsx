import { formatDistanceToNow, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { SignalDefinition, SignalObservation } from "@/api/signals";
import { useDateLocale } from "@/hooks/useDateLocale";

import { formatObservationValue } from "./signalOverlay";

interface Props {
  observation: SignalObservation | null;
  definition: SignalDefinition | null;
  isLoading: boolean;
  onClose: () => void;
}

/**
 * Inline observation popup for the Labs map. Renders the
 * full SignalObservation when the user clicks a marker in the
 * CS-8 overlay; data comes from the same react-query result the
 * overlay already loaded, so no extra API round-trip.
 *
 * Positioned bottom-left (the overlay picker holds bottom-right;
 * the unit-detail panel sits along the right edge). Stacks nicely
 * with both.
 */
export function SignalObservationPanel({
  observation,
  definition,
  isLoading,
  onClose,
}: Props): ReactNode {
  const { t } = useTranslation("signals");
  const dateLocale = useDateLocale();

  if (isLoading) {
    return (
      <div className="pointer-events-auto absolute bottom-2 left-2 z-10 min-w-[260px] rounded-md border border-slate-300 bg-white/95 p-3 text-xs shadow-md">
        <p className="text-slate-500">{t("observationPanel.loading")}</p>
      </div>
    );
  }

  if (!observation) {
    return (
      <div className="pointer-events-auto absolute bottom-2 left-2 z-10 min-w-[260px] rounded-md border border-slate-300 bg-white/95 p-3 text-xs shadow-md">
        <div className="flex items-start justify-between gap-2">
          <p className="text-rose-700">{t("observationPanel.notFound")}</p>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-slate-100"
            aria-label={t("observationPanel.close")}
          >
            ×
          </button>
        </div>
      </div>
    );
  }

  const valueDisplay = formatObservationValue(observation);
  const observedAtIso = observation.time;
  const recordedAtIso = observation.inserted_at;
  const definitionLabel =
    definition?.name ?? observation.signal_code ?? observation.signal_definition_id;

  return (
    <aside
      className="pointer-events-auto absolute bottom-2 left-2 z-10 min-w-[280px] max-w-[360px] rounded-md border border-slate-300 bg-white/95 p-3 text-xs shadow-md"
      role="dialog"
      aria-label={t("observationPanel.title")}
    >
      <header className="flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-500">
            {t("observationPanel.title")}
          </p>
          <h3 className="text-sm font-semibold text-slate-900">{definitionLabel}</h3>
          <p className="font-mono text-[10px] text-slate-500">{observation.signal_code}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] text-slate-600 hover:bg-slate-100"
          aria-label={t("observationPanel.close")}
        >
          ×
        </button>
      </header>

      <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-slate-700">
        <dt className="text-slate-500">{t("observationPanel.value")}</dt>
        <dd className="font-mono tabular-nums text-slate-900">
          {valueDisplay}
          {definition?.unit ? <span className="ms-1 text-slate-500">{definition.unit}</span> : null}
        </dd>

        <dt className="text-slate-500">{t("observationPanel.observedAt")}</dt>
        <dd>
          {formatDistanceToNow(parseISO(observedAtIso), {
            addSuffix: true,
            locale: dateLocale,
          })}
        </dd>

        {recordedAtIso !== observedAtIso ? (
          <>
            <dt className="text-slate-500">{t("observationPanel.recordedAt")}</dt>
            <dd>
              {formatDistanceToNow(parseISO(recordedAtIso), {
                addSuffix: true,
                locale: dateLocale,
              })}
            </dd>
          </>
        ) : null}

        <dt className="text-slate-500">{t("observationPanel.locationMode")}</dt>
        <dd>{t(`observationPanel.locationModes.${observation.location_mode ?? "entity"}`)}</dd>

        {observation.location_point ? (
          <>
            <dt className="text-slate-500">{t("observationPanel.locationPoint")}</dt>
            <dd className="font-mono text-[10px]">
              {observation.location_point.latitude.toFixed(5)},{" "}
              {observation.location_point.longitude.toFixed(5)}
            </dd>
          </>
        ) : null}

        {observation.block_id ? (
          <>
            <dt className="text-slate-500">{t("observationPanel.block")}</dt>
            <dd className="font-mono text-[10px]">{observation.block_id.slice(0, 8)}…</dd>
          </>
        ) : null}

        {observation.template_observation_id ? (
          <>
            <dt className="text-slate-500">{t("observationPanel.template")}</dt>
            <dd className="text-[10px] text-slate-500">
              {observation.template_observation_id === observation.id
                ? t("observationPanel.templateLead")
                : t("observationPanel.templateSibling")}
            </dd>
          </>
        ) : null}
      </dl>

      {observation.notes ? (
        <p className="mt-2 border-t border-slate-200 pt-2 text-[11px] italic text-slate-600">
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
    </aside>
  );
}
