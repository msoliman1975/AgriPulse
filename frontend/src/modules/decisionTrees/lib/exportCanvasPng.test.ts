import { describe, expect, it } from "vitest";

import { buildExportSvg, pngFileName } from "./exportCanvasPng";

const SVG_NS = "http://www.w3.org/2000/svg";

function makeWorldGroup(): SVGGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  const g = document.createElementNS(SVG_NS, "g");
  g.setAttribute("transform", "translate(40 20) scale(0.5)");
  const rect = document.createElementNS(SVG_NS, "rect");
  rect.setAttribute("x", "10");
  rect.setAttribute("y", "12");
  rect.setAttribute("fill", "#ecfdf5");
  g.appendChild(rect);
  svg.appendChild(g);
  document.body.appendChild(svg);
  return g;
}

describe("pngFileName", () => {
  it("slugs the tree code", () => {
    expect(pngFileName("mango_anthracnose_risk_v1")).toBe("mango-anthracnose-risk-v1-tree.png");
  });

  it("falls back when the label has nothing usable", () => {
    expect(pngFileName("")).toBe("decision-tree-tree.png");
    expect(pngFileName("___")).toBe("decision-tree-tree.png");
  });

  it("trims a very long label", () => {
    const name = pngFileName("a".repeat(200));
    expect(name.length).toBeLessThanOrEqual(60 + "-tree.png".length);
  });
});

describe("buildExportSvg", () => {
  it("drops the pan/zoom transform so the export is 1:1", () => {
    const markup = buildExportSvg(makeWorldGroup(), { width: 800, height: 600 });
    expect(markup).not.toContain("translate(40 20)");
  });

  it("keeps the drawn content and sizes the document to the whole graph", () => {
    const markup = buildExportSvg(makeWorldGroup(), { width: 800, height: 600 });
    expect(markup).toContain('viewBox="0 0 800 600"');
    expect(markup).toContain('width="800"');
    expect(markup).toContain("#ecfdf5");
    // A white plate under the graph, so the PNG is not transparent.
    expect(markup).toContain('fill="#ffffff"');
    expect(markup).toContain(SVG_NS);
  });

  it("leaves the live canvas alone", () => {
    const g = makeWorldGroup();
    buildExportSvg(g, { width: 800, height: 600 });
    expect(g.getAttribute("transform")).toBe("translate(40 20) scale(0.5)");
  });
});
