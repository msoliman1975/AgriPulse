import { formatDistanceToNow, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { SignalDefinition, SignalObservation } from "@/api/signals";
import { AnchoredPopup } from "@/components/AnchoredPopup";
import { useDateLocale } from "@/hooks/useDateLocale";

import { formatObservationValue } from "./signalOverlay";

interface Props {
  observation: SignalObservation | null;
  definition: SignalDefinition | null;
  isLoading: boolean;
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
  x,
  y,
  onClose,
}: Props): ReactNode {
  const { t } = useTranslation("signals");
  const dateLocale = useDateLocale();

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
        <p className="text-ap-crit">{t("observationPanel.notFound")}</p>
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
