import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { DateRange } from "../dateRange";

interface Props {
  /** Localised report title, shown as the printout header. */
  title: string;
  /** Farm display name, printed under the title for context. */
  farmName?: string;
  period: DateRange;
  /** Invoked when the user clicks "Export CSV". Omit to hide the button
   * (e.g. while data is still loading). */
  onExportCsv?: () => void;
  children: ReactNode;
}

function formatDay(iso: string): string {
  return iso.slice(0, 10);
}

/**
 * Presentational wrapper each report renders its body inside. Provides
 * the print header (title + farm + period), the Export-CSV and Print
 * buttons, and the `.report-print-area` boundary the print stylesheet
 * keys on. Controls are `.print-hide` so only the report content and
 * its header reach the PDF.
 */
export function ReportShell({ title, farmName, period, onExportCsv, children }: Props): ReactNode {
  const { t } = useTranslation("reports");

  return (
    <section className="report-print-area rounded-xl border border-ap-line bg-ap-panel p-4">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-ap-line pb-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-ap-ink">{title}</h2>
          <p className="mt-0.5 text-xs text-ap-muted">
            {farmName ? <span className="font-medium">{farmName}</span> : null}
            {farmName ? " · " : null}
            {t("shell.period", { from: formatDay(period.since), to: formatDay(period.until) })}
          </p>
        </div>
        <div className="print-hide flex items-center gap-2">
          {onExportCsv ? (
            <button type="button" className="btn btn-ghost text-xs" onClick={onExportCsv}>
              {t("shell.exportCsv")}
            </button>
          ) : null}
          <button type="button" className="btn btn-ghost text-xs" onClick={() => window.print()}>
            {t("shell.print")}
          </button>
        </div>
      </header>
      <div className="mt-4">{children}</div>
    </section>
  );
}
