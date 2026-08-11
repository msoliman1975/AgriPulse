// The inspector's Attributes tab.
//
// Attribute definitions resolve deepest-wins like everything else in the
// taxonomy, but per *code* rather than wholesale: a variety may replace one
// of its crop's fields and leave the rest alone. Standing on a node, the
// question you actually have is "which fields does a block classified here
// get, and which of them can I change from here?" — so that is what this
// answers, splitting them into attached-here and inherited.
//
// Authoring stays on /platform/crops/:id/attributes. That editor is a
// separate, still-working screen; this tab links to it rather than growing a
// second copy of a twenty-control form.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { CropAttributeDefinition } from "@/api/crops";
import type { TaxonomyChain } from "@/modules/admin/lib/cropTaxonomy";
import { scopedAttributes } from "@/modules/admin/lib/scopedAttributes";

export function AttributesPanel({
  chain,
  definitions,
  loading,
}: {
  chain: TaxonomyChain;
  definitions: CropAttributeDefinition[];
  loading: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const path = chain.strain?.path ?? chain.variety?.path ?? chain.crop.code;
  const { attached, inherited } = scopedAttributes(definitions, chain);

  if (loading) return <p className="text-xs text-ap-muted">{t("crops.loading")}</p>;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-ap-muted">{t("catalog.attrsScope", { path })}</p>
        <Link
          to={`/platform/crops/${chain.crop.id}/attributes`}
          className="rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-xs text-ap-primary hover:bg-ap-line/40"
        >
          {t("catalog.attrsAuthor")}
        </Link>
      </div>

      <Group title={t("catalog.attrsAttached", { path })} empty={t("catalog.attrsNoneAttached")}>
        {attached}
      </Group>
      <Group title={t("catalog.attrsInherited")} empty={t("catalog.attrsNoneInherited")}>
        {inherited}
      </Group>
    </section>
  );
}

function Group({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string;
  children: CropAttributeDefinition[];
}): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <div>
      <h3 className="mb-1 text-xs font-medium text-ap-ink">{title}</h3>
      {children.length === 0 ? (
        <p className="rounded-md border border-dashed border-ap-line px-3 py-3 text-center text-[11px] text-ap-muted">
          {empty}
        </p>
      ) : (
        <ul className="divide-y divide-ap-line rounded-md border border-ap-line">
          {children.map((def) => (
            <li key={def.id} className="flex flex-wrap items-baseline gap-2 px-3 py-2">
              <span className="text-sm text-ap-ink">{def.name_en}</span>
              <span className="font-mono text-[10px] text-ap-primary">{def.code}</span>
              <span className="text-[11px] text-ap-muted">
                {t(`cropAttrs.type.${def.value_type}`)}
              </span>
              {def.is_required ? (
                <span className="rounded bg-ap-warn/15 px-1.5 py-0.5 text-[10px] text-ap-warn">
                  {t("cropAttrs.required")}
                </span>
              ) : null}
              {def.show_when ? (
                <span className="text-[11px] text-ap-muted">
                  {t("cropAttrs.gatedOn", { code: def.show_when.code })}
                </span>
              ) : null}
              <span className="ms-auto font-mono text-[10px] text-ap-muted">{def.path}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
