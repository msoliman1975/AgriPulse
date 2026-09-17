/**
 * Where the beta screens live.
 *
 * `/decision-trees-beta` rather than `/decision-trees/beta` on purpose, and
 * for the same reason `/decision-tree-traces` sits outside `/decision-trees/`:
 * a literal segment there would shadow a tree whose code happened to be
 * "beta". `/decision-tree-findings` follows the same shape.
 *
 * Both prefixes exist, tenant and platform, because the two authoring scopes
 * read their own catalogue and their own trees. `authoringScope.ts` decides
 * which one the caller is in; this file only turns that into a path.
 */

import type { AuthoringScope } from "../../lib/authoringScope";

export function betaBasePath(scope: AuthoringScope): string {
  return scope === "platform" ? "/platform/decision-trees-beta" : "/decision-trees-beta";
}

export function betaTreePath(scope: AuthoringScope, code: string): string {
  return `${betaBasePath(scope)}/${code}`;
}

export function findingCataloguePath(scope: AuthoringScope): string {
  return scope === "platform" ? "/platform/decision-tree-findings" : "/decision-tree-findings";
}
