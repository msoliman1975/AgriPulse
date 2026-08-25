// Map marker artwork: one shape per KIND of thing, colour for severity.
//
// The map used to draw three unrelated things as circles — an open alert, a
// signal observation, and a field flag — in three warm colours with no
// legend. Nothing on screen said which circle meant what, so the first
// question anyone asked of the map was "what is that dot".
//
// The rule this module encodes:
//
//   SHAPE says what kind of thing it is.   chip / flag / diamond
//   COLOUR says how bad it is.             severity
//   GLYPH says what it is about.           the alert's action_type
//
// Shape is the first thing the eye separates and it is readable at any
// zoom, which is why it carries kind rather than severity. Colour is a poor
// carrier of kind — the palette is already spent on severity everywhere else
// in the product, and reusing it for two meanings at once is what produced
// the confusion.
//
// MapLibre has no runtime SDF generator, so tinting one white glyph per
// severity is not available to us: an `icon-color` on a non-SDF image does
// nothing. We therefore BAKE the colour into the image and register one
// image per (glyph x severity) combination. That is 8 x 3 = 24 alert chips,
// 3 x 2 flags and 1 diamond — 31 canvas draws once per style load, each a
// few hundred microseconds. The alternative (a pre-built sprite sheet) would
// put the palette in a binary asset where no one editing the severity
// colours would find it.

import type { Map as MlMap } from "maplibre-gl";

// Alert severity as the map's own vocabulary reports it. `blocks_summary`
// buckets the alert table's info/warning/critical down to these — see
// health.ts — so "watch" here is the same thing "warning" is in the API.
export type MarkerSeverity = "critical" | "watch" | "ok";

// The verb a decision-tree leaf chose, which the alert row carries in
// `action_type` (tenant migration 0063).
//
// `alerts.action_type` has NO check constraint. Migration 0015 constrains
// `recommendations.action_type`, and taking that list as the alert list was
// wrong: a tree leaf can name any verb, and three seeded leaves name
// `inspect`, which is not in the recommendations enum. On production every
// open alert that names a verb at all names `inspect`, so reading the
// constraint instead of the data made the glyph inert on the farms that
// have it. When adding a verb here, grep the tree seeds, not migration 0015.
//
// `unknown` is ours, for a leaf that named no verb.
export const ALERT_ACTION_TYPES = [
  "irrigate",
  "fertilize",
  "spray",
  "scout",
  "inspect",
  "harvest_window",
  "prune",
  "no_action",
  "other",
  "unknown",
] as const;

export type AlertActionType = (typeof ALERT_ACTION_TYPES)[number];

export const MARKER_SEVERITIES: readonly MarkerSeverity[] = ["critical", "watch", "ok"] as const;

// One palette, used by every marker. Severity means the same thing whether it
// is on an alert chip or a flag pin, so it must look the same on both.
export const SEVERITY_COLOR: Record<MarkerSeverity, string> = {
  critical: "#A32D2D",
  watch: "#854F0B",
  ok: "#4F6B4A",
};

// The signal-observation diamond is deliberately colourless. An observation
// is a measurement, not a judgement — nobody has said it is good or bad —
// and giving it a severity colour would claim otherwise. Slate reads as
// "information" against both satellite imagery and the health fills.
export const SIGNAL_MARKER_COLOR = "#3F4A55";

/**
 * Map an alert's raw `action_type` onto a glyph we actually have artwork for.
 *
 * Returns `unknown` for null and for any verb the backend grows later, so a
 * new action type degrades to the neutral glyph instead of rendering a blank
 * icon — MapLibre drops a symbol whose `icon-image` does not resolve, which
 * would silently remove the alert from the map entirely.
 */
export function alertActionGlyph(actionType: string | null | undefined): AlertActionType {
  if (!actionType) return "unknown";
  return (ALERT_ACTION_TYPES as readonly string[]).includes(actionType)
    ? (actionType as AlertActionType)
    : "unknown";
}

/** Normalise whatever the summary endpoint said into a palette key. */
export function markerSeverity(raw: string | null | undefined): MarkerSeverity {
  if (raw === "critical") return "critical";
  if (raw === "watch" || raw === "warning") return "watch";
  return "ok";
}

// ---------------------------------------------------------------------------
// Image ids. Built by pure functions so the layer expressions and the
// registration loop cannot drift apart — a mismatch between the two is
// invisible until a marker silently fails to draw.
// ---------------------------------------------------------------------------

export function alertChipImageId(glyph: AlertActionType, severity: MarkerSeverity): string {
  return `ap-alert-${glyph}-${severity}`;
}

export function flagImageId(severity: MarkerSeverity, open: boolean): string {
  return `ap-flag-${severity}-${open ? "open" : "closed"}`;
}

export const SIGNAL_IMAGE_ID = "ap-signal-diamond";

// ---------------------------------------------------------------------------
// Glyph artwork. Stroke paths in a 24x24 box, drawn the way Lucide draws:
// round caps, round joins, no fill. Hand-written rather than pulled from an
// icon package because the project has no icon dependency and a canvas needs
// path data, not React components.
// ---------------------------------------------------------------------------

const GLYPH_PATHS: Record<AlertActionType, string[]> = {
  // A droplet.
  irrigate: ["M12 3 C 12 3, 5 11, 5 15 a 7 7 0 0 0 14 0 c 0 -4, -7 -12, -7 -12 z"],
  // A leaf on a stem — growth, i.e. feeding the plant.
  fertilize: ["M5 19 C 5 10, 11 5, 19 5 C 19 13, 14 19, 5 19 z", "M5 19 L 13 11"],
  // A wand throwing a fan of droplets. Deliberately NOT a drawn spray can:
  // a can outline at this size fills in with its own stroke and reads as a
  // solid blob. Two long strokes and three dots survive the shrink.
  spray: ["M3 21 L 11 13", "M9 15 L 13 19", "M15 5 h .01", "M20 7 h .01", "M17 11 h .01"],
  // A magnifier — going out to look over the block.
  scout: ["M11 18 a 7 7 0 1 1 0 -14 a 7 7 0 0 1 0 14 z", "M16.5 16.5 L 21 21"],
  // An eye — looking closely at one thing. Kept distinct from `scout`
  // because the two verbs send somebody to different work: scouting walks
  // the block, inspecting examines what is already suspected.
  inspect: [
    "M2 12 s 4 -6 10 -6 s 10 6 10 6 s -4 6 -10 6 s -10 -6 -10 -6 z",
    "M12 15 a 3 3 0 1 1 0 -6 a 3 3 0 0 1 0 6 z",
  ],
  // A basket.
  harvest_window: ["M3 9 h 18 l -2 11 H 5 z", "M8 9 L 12 3 L 16 9"],
  // Open shears.
  prune: [
    "M7 4 L 17 18",
    "M17 4 L 7 18",
    "M6 20 a 2.5 2.5 0 1 1 0 -5 a 2.5 2.5 0 0 1 0 5 z",
    "M18 20 a 2.5 2.5 0 1 1 0 -5 a 2.5 2.5 0 0 1 0 5 z",
  ],
  // A bar — nothing to do.
  no_action: ["M5 12 h 14"],
  // Three dots.
  other: ["M6 12 h .01", "M12 12 h .01", "M18 12 h .01"],
  // An exclamation, for an alert whose verb we do not know.
  unknown: ["M12 5 v 8", "M12 18 h .01"],
};

// A pennant on a pole. Drawn as a fill (the pennant) plus a stroke (the
// pole), because a flag has to read as a flag at 14 screen pixels and an
// outline-only pennant closes up into a blob at that size.
const FLAG_PENNANT = "M8 4 L 20 8.5 L 8 13 z";
const FLAG_POLE = "M7 3 V 21";

// ---------------------------------------------------------------------------
// Geometry. All numbers below are IMAGE pixels at pixelRatio 2, so a value of
// 48 lands as 24 CSS pixels on screen.
// ---------------------------------------------------------------------------

const RATIO = 2;

const CHIP_H = 48; // 24 CSS px tall
const CHIP_PAD = 10;
const CHIP_GLYPH = 32; // 16 CSS px glyph. Below this, a glyph carrying
// more than three marks closes up into a blob under its own stroke.
const CHIP_GAP = 6;
const CHIP_TEXT_MIN = 20; // room for a single digit before stretching
const CHIP_RADIUS = 12;
const CHIP_BORDER = 3;

const CHIP_TEXT_X = CHIP_PAD + CHIP_GLYPH + CHIP_GAP;
const CHIP_W = CHIP_TEXT_X + CHIP_TEXT_MIN + CHIP_PAD;

/**
 * The stretch + content boxes handed to `map.addImage`.
 *
 * `icon-text-fit: "both"` grows the image to wrap the count text. Only the
 * region to the RIGHT of the glyph is listed in `stretchX`, so a chip
 * carrying "12" gets wider without the droplet turning into an ellipse.
 * `content` is where MapLibre puts the text, which is why it starts after the
 * glyph rather than at the chip's edge.
 */
export const CHIP_IMAGE_OPTIONS = {
  pixelRatio: RATIO,
  stretchX: [[CHIP_TEXT_X, CHIP_W - CHIP_PAD]] as [number, number][],
  stretchY: [[CHIP_RADIUS, CHIP_H - CHIP_RADIUS]] as [number, number][],
  content: [CHIP_TEXT_X, 0, CHIP_W - CHIP_PAD, CHIP_H] as [number, number, number, number],
};

// The pennant is drawn so the FOOT OF THE POLE sits at the bottom centre of
// the image. That lets the layer use `icon-anchor: "bottom"` and have the
// pole plant itself exactly on the coordinate, the way a real flag marks a
// spot. Anchoring the image centre instead would float the pin half its own
// height north of the thing the scout was standing next to.
const FLAG_SCALE = 2; // 24-box units -> image px
const FLAG_DX = 14; // puts the pole (x=7 in the box) on the centre line
const FLAG_DY = 2;
const FLAG_W = 56;
const FLAG_H = 46;
const PIN_W = 40;
const PIN_H = 40;

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------

type Ctx = CanvasRenderingContext2D;

function canvas2d(w: number, h: number): Ctx | null {
  const el = document.createElement("canvas");
  el.width = w;
  el.height = h;
  const ctx = el.getContext("2d");
  if (!ctx) return null;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  return ctx;
}

function roundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Stroke a set of 24-box path strings scaled into a `size` square at (x, y). */
function strokeGlyph(
  ctx: CanvasRenderingContext2D,
  paths: readonly string[],
  x: number,
  y: number,
  size: number,
  color: string,
  weight: number,
): void {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(size / 24, size / 24);
  ctx.strokeStyle = color;
  // The scale above multiplies the line width too, so undo it to keep the
  // stroke the requested weight in image pixels rather than in glyph units.
  ctx.lineWidth = (weight * 24) / size;
  for (const d of paths) ctx.stroke(new Path2D(d));
  ctx.restore();
}

/**
 * An alert: a severity-coloured chip carrying the action glyph and, once
 * MapLibre fits the text, the number of open alerts on that block.
 *
 * The count is the reason this replaced a plain dot. `alert_count` has been
 * on the feature since the summary endpoint shipped, but the circle layer
 * had nowhere to put it, so a block with one alert and a block with eleven
 * looked identical.
 */
function drawAlertChip(glyph: AlertActionType, severity: MarkerSeverity): Ctx | null {
  const ctx = canvas2d(CHIP_W, CHIP_H);
  if (!ctx) return null;

  const half = CHIP_BORDER / 2;
  roundedRect(ctx, half, half, CHIP_W - CHIP_BORDER, CHIP_H - CHIP_BORDER, CHIP_RADIUS);
  ctx.fillStyle = SEVERITY_COLOR[severity];
  ctx.fill();
  // A white keyline. Every marker on this map sits over satellite imagery,
  // which is dark, mid and bright within one block; without the keyline a
  // dark red chip disappears over a shadowed tree line.
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = CHIP_BORDER;
  ctx.stroke();

  strokeGlyph(
    ctx,
    GLYPH_PATHS[glyph],
    CHIP_PAD,
    (CHIP_H - CHIP_GLYPH) / 2,
    CHIP_GLYPH,
    "#ffffff",
    // Weight as a fraction of the glyph box, matching what an icon set uses
    // at this size. Heavier reads bolder over imagery but swallows detail.
    3,
  );
  return ctx;
}

/**
 * A field flag: the pennant a scout raised, in the severity THEY chose
 * (`field_flags.severity`, tenant migration 0081).
 *
 * Open flags are filled; closed ones are a hollow outline in the same
 * colour. A closed pin stays on the map until its `pin_until` runs out, so
 * the layer has to say which work is finished without changing what the pin
 * is about — the same rule the old circle layer used, kept deliberately.
 */
function drawFlag(severity: MarkerSeverity, open: boolean): Ctx | null {
  const ctx = canvas2d(FLAG_W, FLAG_H);
  if (!ctx) return null;
  const color = SEVERITY_COLOR[severity];

  ctx.save();
  ctx.translate(FLAG_DX, FLAG_DY);
  ctx.scale(FLAG_SCALE, FLAG_SCALE);
  const scale = FLAG_SCALE;

  const pennant = new Path2D(FLAG_PENNANT);
  // White under the pennant first: a hollow closed flag over bright bare soil
  // has almost no contrast, and the halo is what keeps its outline readable.
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 5 / scale;
  ctx.stroke(pennant);
  ctx.stroke(new Path2D(FLAG_POLE));

  if (open) {
    ctx.fillStyle = color;
    ctx.fill(pennant);
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.4 / scale;
  ctx.stroke(pennant);
  ctx.lineWidth = 3 / scale;
  ctx.stroke(new Path2D(FLAG_POLE));
  ctx.restore();

  return ctx;
}

/**
 * A signal observation: a hollow diamond in one neutral colour.
 *
 * Deliberately the quietest of the three. An observation is a reading
 * somebody took, not a problem somebody found, and the map should not make
 * it compete with an alert for attention.
 */
function drawSignalDiamond(): Ctx | null {
  const ctx = canvas2d(PIN_W, PIN_H);
  if (!ctx) return null;
  const c = PIN_W / 2;
  const r = c - 6;

  ctx.beginPath();
  ctx.moveTo(c, c - r);
  ctx.lineTo(c + r, c);
  ctx.lineTo(c, c + r);
  ctx.lineTo(c - r, c);
  ctx.closePath();

  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 6;
  ctx.stroke();
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.strokeStyle = SIGNAL_MARKER_COLOR;
  ctx.lineWidth = 3.5;
  ctx.stroke();
  return ctx;
}

/**
 * Register every marker image on the map.
 *
 * Idempotent: MapLibre throws on a duplicate image id, and this runs again
 * on every `styledata` — a basemap switch drops the image registry along
 * with the style, so re-adding is exactly what has to happen.
 *
 * Silently does nothing where there is no 2D canvas (jsdom in the unit
 * tests). The layers still get added; they just draw no symbols, which is
 * the correct outcome for a test that is not asserting on pixels.
 */
export function registerMarkerImages(map: MlMap): void {
  const add = (id: string, ctx: Ctx | null, options?: Parameters<MlMap["addImage"]>[2]) => {
    if (!ctx) return;
    const image = ctx.getImageData(0, 0, ctx.canvas.width, ctx.canvas.height);
    if (map.hasImage(id)) map.removeImage(id);
    map.addImage(id, image, options);
  };

  for (const glyph of ALERT_ACTION_TYPES) {
    for (const severity of MARKER_SEVERITIES) {
      add(alertChipImageId(glyph, severity), drawAlertChip(glyph, severity), CHIP_IMAGE_OPTIONS);
    }
  }
  for (const severity of MARKER_SEVERITIES) {
    for (const open of [true, false]) {
      add(flagImageId(severity, open), drawFlag(severity, open), { pixelRatio: RATIO });
    }
  }
  add(SIGNAL_IMAGE_ID, drawSignalDiamond(), { pixelRatio: RATIO });
}

// ---------------------------------------------------------------------------
// Legend artwork.
//
// The legend draws from the SAME functions the map does, as data URLs rather
// than as a second set of hand-made SVGs. A legend that is redrawn separately
// drifts from the map the first time a colour changes, and a legend that
// disagrees with the map is worse than none.
// ---------------------------------------------------------------------------

function dataUrl(ctx: Ctx | null): string | null {
  if (!ctx) return null;
  try {
    return ctx.canvas.toDataURL("image/png");
  } catch {
    // Guarded rather than assumed: a tainted or zero-sized canvas throws
    // here, and a missing legend swatch must not take the console down.
    return null;
  }
}

export function alertChipPreview(glyph: AlertActionType, severity: MarkerSeverity): string | null {
  return dataUrl(drawAlertChip(glyph, severity));
}

export function flagPreview(severity: MarkerSeverity, open: boolean): string | null {
  return dataUrl(drawFlag(severity, open));
}

export function signalPreview(): string | null {
  return dataUrl(drawSignalDiamond());
}
