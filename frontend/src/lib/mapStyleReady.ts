import type { Map as MapLibreMap } from "maplibre-gl";

/**
 * Whether the map's STYLE can take sources and layers now.
 *
 * Not `map.isStyleLoaded()`. In MapLibre 4 that also requires every source to
 * have finished loading its tiles (`Style.loaded()` walks the source caches),
 * so on a map with tiles in flight it is false, and the usual fallbacks fail
 * in two ways:
 *
 *  * `map.once("load", fn)` never runs: `load` fired long ago, so the update
 *    is silently dropped until something else re-runs the effect.
 *  * `map.once("idle", fn)` runs, but only after EVERY tile on screen has
 *    arrived, so a slow source holds up everything behind it. With the
 *    latest-photo layer loading (~25 tiles at ~1 s each), the console's index
 *    pixels were not even added until it finished.
 *
 * `addSource` / `addLayer` need only the style document, which is what
 * `style._loaded` says. When it is false the map has not fired `load` yet, so
 * `map.once("load", ...)` is the right wait.
 */
export function isStyleReady(map: MapLibreMap): boolean {
  return Boolean(map.style?._loaded);
}
