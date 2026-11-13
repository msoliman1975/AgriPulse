import type { SourceAlias } from "@/api/sources";
import type { PillKind } from "@/components/Pill";

export const CONFIDENCE_PILL: Record<string, PillKind> = {
  high: "ok",
  medium: "info",
  low: "warn",
  expert_inference: "neutral",
};

/** Short labels for the documents the library was imported from. */
const DOCUMENT_SHORT: Record<string, string> = {
  medjool_manual_1_7: "Manual 1.7",
  medjool_manual_1_7_annex_a: "Manual 1.7 · Annex A",
  medjool_manual_1_7_annex_b: "Manual 1.7 · Annex B",
  medjool_trees_v2: "Trees v2",
};

export function documentLabel(code: string): string {
  return DOCUMENT_SHORT[code] ?? code;
}

/** "Manual 1.7 [15] · Trees v2 [41]" — how each document numbers this source. */
export function aliasLabel(aliases: SourceAlias[]): string {
  return aliases.map((a) => `${documentLabel(a.document_code)} [${a.ref_number}]`).join(" · ");
}

/** The link to open: the DOI resolver when there is a DOI, else the URL. */
export function sourceHref(source: { doi: string | null; url: string | null }): string | null {
  if (source.doi) return `https://doi.org/${source.doi}`;
  return source.url;
}
