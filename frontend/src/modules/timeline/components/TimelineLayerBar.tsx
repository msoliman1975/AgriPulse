// What the replay draws — one row of checkboxes, nothing behind a popover.
//
// The same shape as the Farm Console's `MapLayerBar`, and for the same
// reason: these are switches a reader flips while watching, and a switch
// two clicks deep is a switch nobody finds. A checkbox is a checkbox.
//
// Two groups, because they answer different questions. The first is what
// the map draws AROUND the data — the pixels, the farm border, the block
// borders. The second is the seven kinds of datapoint, which are the data
// itself. The split matches the console's bar-versus-rail split so a
// reader who has learned one screen has learned this one.
//
// The datapoint switches drive the map AND the rail, because the replay's
// rule is that both halves read the same frame. They deliberately do NOT
// drive the scrubber's ticks: the ticks say where in the window something
// happened, and a reader who has hidden alerts still needs to find the day
// one was raised in order to switch them back on.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TimelineEventKind } from "@/api/timeline";
import { LAYER_KINDS, type TimelineLayerState } from "../lib/layerState";

interface Props {
  layers: TimelineLayerState;
  onChange: (next: TimelineLayerState) => void;
  /**
   * Kinds the API dropped because this reader's role cannot see them.
   * Their switch is disabled and says so, rather than offering a control
   * that turns on nothing.
   */
  omittedKinds: readonly TimelineEventKind[];
  className?: string;
}

export function TimelineLayerBar({ layers, onChange, omittedKinds, className }: Props): ReactNode {
  const { t } = useTranslation("timeline");
  const omitted = new Set(omittedKinds);

  const setKind = (kind: TimelineEventKind, on: boolean): void =>
    onChange({ ...layers, kinds: { ...layers.kinds, [kind]: on } });

  return (
    <div
      className={"flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 " + (className ?? "")}
      role="group"
      aria-label={t("layers.regionLabel")}
    >
      <span className="flex-none text-meta font-medium uppercase text-ap-muted">
        {t("layers.map")}
      </span>
      <Check
        label={t("layers.pixels")}
        checked={layers.pixels}
        onChange={() => onChange({ ...layers, pixels: !layers.pixels })}
      />
      <Check
        label={t("layers.farmBoundary")}
        checked={layers.farmBoundary}
        onChange={() => onChange({ ...layers, farmBoundary: !layers.farmBoundary })}
      />
      <Check
        label={t("layers.blocks")}
        checked={layers.blocks}
        onChange={() => onChange({ ...layers, blocks: !layers.blocks })}
      />

      <Rule />

      <span className="flex-none text-meta font-medium uppercase text-ap-muted">
        {t("layers.datapoints")}
      </span>
      {LAYER_KINDS.map((kind) => (
        <Check
          key={kind}
          label={t(`kind.${kind}`)}
          checked={layers.kinds[kind] && !omitted.has(kind)}
          disabled={omitted.has(kind)}
          title={omitted.has(kind) ? t("layers.omitted") : undefined}
          onChange={() => setKind(kind, !layers.kinds[kind])}
        />
      ))}
    </div>
  );
}

function Rule(): ReactNode {
  return <span className="h-4 w-px flex-none bg-ap-line" aria-hidden="true" />;
}

function Check({
  label,
  checked,
  disabled,
  title,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  title?: string;
  onChange: () => void;
}): ReactNode {
  return (
    <label
      title={title ?? label}
      className={
        "flex flex-none items-center gap-1.5 whitespace-nowrap text-sm " +
        (disabled ? "cursor-not-allowed text-ap-muted/60" : "cursor-pointer text-ap-ink")
      }
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={onChange}
        className="h-3.5 w-3.5 accent-ap-primary"
      />
      <span>{label}</span>
    </label>
  );
}
