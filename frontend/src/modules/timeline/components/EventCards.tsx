// The dock: up to six numbered cards down the side of the map.
//
// The map answers "where"; a 30-pixel icon over satellite imagery cannot
// also answer "what". The card carries the words, the number carries the
// tie back to the spot, and the rail underneath keeps the full list — the
// dock never replaces it.
//
// Slot allocation is in `lib/cards.ts` and is deliberately not here: which
// six, and which number each one holds, is arithmetic over time and has to
// be testable without a DOM.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Pill } from "@/components/Pill";
import { localizedField } from "@/lib/localizedField";
import { badgeColor } from "../lib/cardArtwork";
import type { CardedEvent } from "../lib/cards";
import { eventPillKind, eventTitle } from "../lib/eventText";
import { itemLinkFor } from "../lib/itemLink";

interface Props {
  farmId: string;
  cards: readonly CardedEvent[];
  /** Visible datapoints with no card. 0 hides the row. */
  overflow: number;
  /** Hovered or clicked. Its marker lifts and the connector is drawn. */
  activeEventId: string | null;
  /**
   * Called with the event and where its connector should start, in
   * coordinates relative to `containerRef`. Null on leave.
   */
  onActivate: (eventId: string | null, from: { x: number; y: number } | null) => void;
  onSelect: (eventId: string) => void;
  /** The dock's positioning parent — the same box the map fills. */
  containerRef: React.RefObject<HTMLElement | null>;
  /** Focus the rail without picking any one datapoint. */
  onShowAll: () => void;
}

export function EventCards({
  farmId,
  cards,
  overflow,
  activeEventId,
  onActivate,
  onSelect,
  containerRef,
  onShowAll,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("timeline");

  if (cards.length === 0) return null;

  // Where the connector leaves the card: the middle of its map-facing
  // edge. Measured on hover only — the card does not move while the map
  // pans, so there is nothing to recompute per frame.
  const anchorOf = (el: HTMLElement): { x: number; y: number } | null => {
    const parent = containerRef.current;
    if (!parent) return null;
    const card = el.getBoundingClientRect();
    const box = parent.getBoundingClientRect();
    return { x: card.right - box.left, y: card.top - box.top + card.height / 2 };
  };

  return (
    <div className="pointer-events-none absolute bottom-3 left-3 top-24 z-10 flex flex-col items-start justify-start">
      <ul
        className="pointer-events-auto flex min-h-0 w-[232px] flex-col gap-1.5 overflow-y-auto pe-1"
        aria-label={t("cards.listLabel")}
      >
        {cards.map((card) => {
          const active = activeEventId === card.event.id;
          const link = itemLinkFor(card.event, farmId);
          const blockLabel =
            localizedField(i18n.language, card.event.block_name, card.event.block_name_ar) ??
            card.event.block_code;
          return (
            <li
              key={card.key}
              className={[
                "tl-card tl-card--fresh rounded-card border bg-ap-panel/95 px-2.5 py-2 shadow-sm backdrop-blur-sm",
                active ? "border-ap-primary" : "border-ap-line",
              ].join(" ")}
              // Opacity carries age here exactly as it does on the marker
              // and on the rail row, floored so the words stay readable.
              style={{ opacity: 0.5 + card.opacity * 0.5 }}
              onMouseEnter={(e) => onActivate(card.event.id, anchorOf(e.currentTarget))}
              onMouseLeave={() => onActivate(null, null)}
              onFocus={(e) => onActivate(card.event.id, anchorOf(e.currentTarget))}
              onBlur={() => onActivate(null, null)}
            >
              <div className="flex items-start gap-2">
                <span
                  className="mt-0.5 grid h-[18px] min-w-[18px] shrink-0 place-items-center rounded-full border-2 border-white text-[11px] font-bold leading-none text-white tabular-nums"
                  style={{ backgroundColor: badgeColor(card.event.kind, card.event.severity) }}
                  aria-hidden="true"
                >
                  {card.number}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Pill kind={eventPillKind(card.event)}>{t(`kind.${card.event.kind}`)}</Pill>
                    {blockLabel ? (
                      <span className="truncate text-meta text-ap-muted">{blockLabel}</span>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    onClick={() => onSelect(card.event.id)}
                    className="mt-1 block w-full text-start text-sm text-ap-ink hover:underline"
                  >
                    {eventTitle(card.event, t, i18n.language)}
                  </button>
                  {link ? (
                    <Link
                      to={link}
                      className="mt-1 inline-block text-meta text-ap-primary hover:underline"
                    >
                      {t("cards.open")}
                    </Link>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}

        {overflow > 0 ? (
          <li>
            <button
              type="button"
              onClick={onShowAll}
              className="w-full rounded-card border border-dashed border-ap-line bg-ap-panel/90 px-2.5 py-1.5 text-meta text-ap-muted hover:text-ap-ink"
            >
              {t("cards.more", { count: overflow })}
            </button>
          </li>
        ) : null}
      </ul>
    </div>
  );
}
