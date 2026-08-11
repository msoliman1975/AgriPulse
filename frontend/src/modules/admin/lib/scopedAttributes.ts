// Which attribute definitions are in scope at a taxonomy node.
//
// Unlike phenology and size classes — which resolve wholesale, the deepest
// non-NULL level replacing its parent entirely — attribute definitions
// resolve per *code*: a variety may replace one of its crop's fields and
// inherit the rest untouched. So the answer at any node is a merged set, and
// the useful split is "attached here" (editable from this node) versus
// "inherited from above" (editable only where it is attached).
//
// Mirrors the backend's resolved-attributes endpoint, computed over the admin
// list the console already holds rather than costing a second request.

import type { CropAttributeDefinition } from "@/api/crops";
import type { TaxonomyChain } from "@/modules/admin/lib/cropTaxonomy";

export interface ScopedAttributes {
  attached: CropAttributeDefinition[];
  inherited: CropAttributeDefinition[];
}

export function scopedAttributes(
  definitions: CropAttributeDefinition[],
  chain: TaxonomyChain,
): ScopedAttributes {
  const path = chain.strain?.path ?? chain.variety?.path ?? chain.crop.code;
  // "mango.alphonso.a1" is in scope at mango, mango.alphonso and itself.
  const ancestors = new Set<string>();
  const parts = path.split(".");
  for (let i = 1; i <= parts.length; i += 1) ancestors.add(parts.slice(0, i).join("."));

  const inScope = definitions.filter((d) => ancestors.has(d.path));
  // The deeper path wins per code. A tie is impossible — path + code is
  // unique — so the longer path is an adequate depth comparison.
  const winner = new Map<string, CropAttributeDefinition>();
  for (const def of inScope) {
    const current = winner.get(def.code);
    if (!current || def.path.length > current.path.length) winner.set(def.code, def);
  }
  const resolved = [...winner.values()].sort((a, b) => a.sort_order - b.sort_order);
  return {
    attached: resolved.filter((d) => d.path === path),
    inherited: resolved.filter((d) => d.path !== path),
  };
}
