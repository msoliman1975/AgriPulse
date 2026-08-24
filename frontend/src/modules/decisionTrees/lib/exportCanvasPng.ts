// Export the tree canvas as a PNG.
//
// The canvas is plain SVG with every style set as a presentation
// attribute (no CSS classes, no external images, no web fonts), so a
// clone of the world <g> serialises to a self-contained document. We
// draw that document into a <canvas> and hand the user a PNG of the
// WHOLE graph at 1:1 — not of the current zoom/pan window.

const SVG_NS = "http://www.w3.org/2000/svg";

export interface ExportSize {
  width: number;
  height: number;
}

/** Turn a slug-ish label into a safe file stem. */
export function pngFileName(label: string): string {
  const slug = (label || "decision-tree")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return `${slug || "decision-tree"}-tree.png`;
}

/** Serialise the world group into a standalone SVG document string.
 *  Exported for tests. */
export function buildExportSvg(worldGroup: SVGGElement, size: ExportSize): string {
  const clone = worldGroup.cloneNode(true) as SVGGElement;
  clone.removeAttribute("transform");

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("xmlns", SVG_NS);
  svg.setAttribute("width", String(size.width));
  svg.setAttribute("height", String(size.height));
  svg.setAttribute("viewBox", `0 0 ${size.width} ${size.height}`);

  const background = document.createElementNS(SVG_NS, "rect");
  background.setAttribute("x", "0");
  background.setAttribute("y", "0");
  background.setAttribute("width", String(size.width));
  background.setAttribute("height", String(size.height));
  background.setAttribute("fill", "#ffffff");

  svg.appendChild(background);
  svg.appendChild(clone);
  return new XMLSerializer().serializeToString(svg);
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("could not rasterize the canvas SVG"));
    img.src = src;
  });
}

function triggerDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser a tick to start the download before we drop the URL.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Render the graph to a PNG and start a download. Rejects if the
 *  browser refuses to rasterize; the caller shows the error. */
export async function exportCanvasPng(
  worldGroup: SVGGElement,
  size: ExportSize,
  fileName: string,
  pixelRatio = 2,
): Promise<void> {
  const markup = buildExportSvg(worldGroup, size);
  const svgUrl = URL.createObjectURL(new Blob([markup], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = await loadImage(svgUrl);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(size.width * pixelRatio));
    canvas.height = Math.max(1, Math.round(size.height * pixelRatio));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("2d canvas context unavailable");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!png) throw new Error("could not encode the PNG");
    triggerDownload(png, fileName);
  } finally {
    URL.revokeObjectURL(svgUrl);
  }
}
