// The DOM node for one carded datapoint's map marker.
//
// Split out of `TimelineMap` so the element can be built and asserted
// without a WebGL context: jsdom has no canvas, so a test that mounts the
// map draws nothing, but this is plain DOM and can be checked directly.
//
// Everything about how it LOOKS lives in `styles/index.css` under
// `.tl-mark`. Only the number, the colour and the artwork come from here,
// because only those three are per-datapoint.

/** One carded datapoint, resolved down to what the map needs to draw it. */
export interface CardMark {
  eventId: string;
  /** 1..6. The tie between the card and the mark. */
  number: number;
  coordinates: [number, number];
  /** 0..1 from the fade curve. */
  opacity: number;
  /** Severity colour, already resolved by the caller. */
  color: string;
  /**
   * A data URL for the kind's artwork, or null for a block-scoped
   * datapoint, which draws the numbered ring alone.
   */
  iconUrl: string | null;
  blockScoped: boolean;
  /** What a screen reader and a hover title say. */
  label: string;
}

export function buildMarkElement(mark: CardMark): HTMLDivElement {
  const el = document.createElement("div");
  el.className = "tl-mark tl-mark--fresh";
  el.dataset.eventId = mark.eventId;
  // A button rather than a div would be better for the keyboard, but
  // MapLibre owns this node's position and a focused marker scrolling into
  // view fights the map's own camera. The cards beside the map are the
  // keyboard path; these are pointer targets.
  el.setAttribute("role", "img");

  if (mark.iconUrl !== null) {
    const img = document.createElement("img");
    img.className = "tl-mark-glyph";
    img.alt = "";
    el.appendChild(img);
  }

  const badge = document.createElement("span");
  badge.className = "tl-mark-badge";
  el.appendChild(badge);

  updateMarkElement(el, mark);
  return el;
}

/** Write the per-datapoint values onto an element `buildMarkElement` made. */
export function updateMarkElement(el: HTMLDivElement, mark: CardMark): void {
  el.style.opacity = String(mark.opacity);
  el.title = mark.label;
  el.setAttribute("aria-label", mark.label);
  el.classList.toggle("tl-mark--block", mark.blockScoped);

  const img = el.querySelector<HTMLImageElement>(".tl-mark-glyph");
  if (img && mark.iconUrl !== null && img.getAttribute("src") !== mark.iconUrl) {
    img.src = mark.iconUrl;
  }

  const badge = el.querySelector<HTMLSpanElement>(".tl-mark-badge");
  if (badge) {
    const text = String(mark.number);
    if (badge.textContent !== text) badge.textContent = text;
    badge.style.backgroundColor = mark.color;
  }
}
