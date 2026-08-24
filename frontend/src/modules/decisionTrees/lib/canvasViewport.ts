// Pan / zoom maths for the decision-tree canvas.
//
// The canvas renders every node inside one <g> with a single
// transform: `translate(tx, ty) scale(scale)`. World coordinates are
// the pixel coordinates `treeLayout` produces; screen coordinates are
// pixels inside the canvas viewport element.
//
//   screen = world * scale + t
//   world  = (screen - t) / scale
//
// Keeping this in one pure module means the drag handlers, the zoom
// buttons and the fit-to-screen button all agree, and it can be
// tested without a DOM.

export interface Viewport {
  scale: number;
  tx: number;
  ty: number;
}

export interface Size {
  width: number;
  height: number;
}

export const MIN_SCALE = 0.2;
export const MAX_SCALE = 2.5;
/** Step used by the +/- buttons and the keyboard shortcuts. */
export const ZOOM_STEP = 1.2;

export const IDENTITY_VIEWPORT: Viewport = { scale: 1, tx: 0, ty: 0 };

export function clampScale(scale: number): number {
  if (!Number.isFinite(scale)) return 1;
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

export function screenToWorld(
  view: Viewport,
  screenX: number,
  screenY: number,
): {
  x: number;
  y: number;
} {
  return { x: (screenX - view.tx) / view.scale, y: (screenY - view.ty) / view.scale };
}

export function worldToScreen(
  view: Viewport,
  worldX: number,
  worldY: number,
): {
  x: number;
  y: number;
} {
  return { x: worldX * view.scale + view.tx, y: worldY * view.scale + view.ty };
}

/** Zoom by `factor`, keeping the world point currently under
 *  (anchorX, anchorY) — a screen coordinate — in the same place. */
export function zoomAt(view: Viewport, factor: number, anchorX: number, anchorY: number): Viewport {
  const nextScale = clampScale(view.scale * factor);
  if (nextScale === view.scale) return view;
  const world = screenToWorld(view, anchorX, anchorY);
  return {
    scale: nextScale,
    tx: anchorX - world.x * nextScale,
    ty: anchorY - world.y * nextScale,
  };
}

/** Zoom about the centre of the viewport — used by the +/- buttons
 *  and the keyboard shortcuts, where there is no cursor anchor. */
export function zoomAtCentre(view: Viewport, factor: number, viewport: Size): Viewport {
  return zoomAt(view, factor, viewport.width / 2, viewport.height / 2);
}

/** Scale the whole graph to fit the viewport and centre it. Never
 *  magnifies past 1:1 — a three-node tree should not fill the screen
 *  with giant boxes. */
export function fitToViewport(content: Size, viewport: Size, padding = 24): Viewport {
  if (
    !(content.width > 0) ||
    !(content.height > 0) ||
    !(viewport.width > 0) ||
    !(viewport.height > 0)
  ) {
    return IDENTITY_VIEWPORT;
  }
  const usableW = Math.max(1, viewport.width - padding * 2);
  const usableH = Math.max(1, viewport.height - padding * 2);
  const scale = clampScale(Math.min(usableW / content.width, usableH / content.height, 1));
  return {
    scale,
    tx: (viewport.width - content.width * scale) / 2,
    ty: (viewport.height - content.height * scale) / 2,
  };
}

/** Percentage shown in the toolbar, e.g. 0.835 -> 84. */
export function zoomPercent(view: Viewport): number {
  return Math.round(view.scale * 100);
}
