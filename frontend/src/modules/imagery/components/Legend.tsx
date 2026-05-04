import { useTranslation } from "react-i18next";

interface Props {
  /** Index value at the lowest stop (e.g. -0.2 for NDVI). */
  min: number;
  /** Index value at the highest stop (e.g. 0.9 for NDVI). */
  max: number;
  /** Colour ramp endpoints; defaults match the TiTiler `greens` colormap. */
  fromColor?: string;
  toColor?: string;
}

/**
 * Static gradient legend rendered next to the map. Pure presentation
 * — no data fetching. Numbers are formatted with Latin digits in
 * both en and ar per ARCHITECTURE.md § 11.
 */
export function Legend({
  min,
  max,
  fromColor = "#fffbea",
  toColor = "#166534",
}: Props): JSX.Element {
  const { t } = useTranslation("imagery");
  const fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

  return (
    <div
      className="rounded border border-slate-200 bg-white p-3 text-xs text-slate-700"
      role="figure"
      aria-label={t("legend.title")}
    >
      <p className="mb-2 font-semibold">{t("legend.title")}</p>
      <div
        className="h-3 w-full rounded"
        style={{
          background: `linear-gradient(to right, ${fromColor}, ${toColor})`,
        }}
      />
      <div className="mt-1 flex justify-between">
        <span>
          <span className="block">{fmt.format(min)}</span>
          <span className="block text-slate-500">{t("legend.low")}</span>
        </span>
        <span className="text-center">
          <span className="block">{fmt.format((min + max) / 2)}</span>
          <span className="block text-slate-500">{t("legend.mid")}</span>
        </span>
        <span className="text-right">
          <span className="block">{fmt.format(max)}</span>
          <span className="block text-slate-500">{t("legend.high")}</span>
        </span>
      </div>
    </div>
  );
}
