import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { CustomFieldCells, CustomFieldDef } from "@/api/reports";
import { Th, Td } from "@/components/Table";

import { fieldLabel, formatCustomCell, isNumericField } from "../customFields";

/**
 * The header and body cells for tenant-defined report columns.
 *
 * Four reports render these identically; only the table they are appended to
 * differs. Keeping them here means a change to how a multi-select or a stale
 * signal reading looks lands in all four at once, rather than in whichever
 * three somebody remembered.
 */

export function CustomHeaderCells({ defs }: { defs: CustomFieldDef[] }): ReactNode {
  const { i18n } = useTranslation("reports");
  return (
    <Fragment>
      {defs.map((def) => (
        <Th
          key={def.key}
          scope="col"
          className={isNumericField(def) ? "text-end" : undefined}
          // Tenant-written labels can be Arabic on an English page and the
          // reverse, so the direction follows the text, not the page.
          dir="auto"
        >
          {fieldLabel(def, i18n.language)}
        </Th>
      ))}
    </Fragment>
  );
}

export function CustomBodyCells({
  defs,
  cells,
}: {
  defs: CustomFieldDef[];
  cells: CustomFieldCells;
}): ReactNode {
  const { t, i18n } = useTranslation("reports");
  return (
    <Fragment>
      {defs.map((def) => {
        const value = cells[def.key];
        const text = formatCustomCell(def, cells, i18n.language);
        return (
          <Td
            key={def.key}
            className={isNumericField(def) ? "text-end tabular-nums" : undefined}
            dir="auto"
          >
            {text ? (
              <>
                <span className="text-ap-ink">{text}</span>
                {/* A signal cell says when it was read. A 3-week-old count
                    next to today's index number is a different claim from a
                    reading taken this morning, and the date is the only thing
                    on the row that says which one it is. */}
                {value?.observed_at ? (
                  <div className="text-[10px] text-ap-muted">{value.observed_at.slice(0, 10)}</div>
                ) : null}
              </>
            ) : (
              <span className="text-ap-muted">{t("customFields.noValue")}</span>
            )}
          </Td>
        );
      })}
    </Fragment>
  );
}
