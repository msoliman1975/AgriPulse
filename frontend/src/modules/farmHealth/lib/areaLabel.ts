// An area's name, in the reader's language.
//
// Built from the parts `buildAreas` returns rather than assembled as English
// inside that library. A name joined from English words there would arrive on
// the Arabic screen in English, which is how this app shipped English under
// Arabic names once before.

import type { TFunction } from "i18next";

import type { AreaName } from "./areas";

export function areaLabel(t: TFunction, name: AreaName, spots: number): string {
  switch (name.kind) {
    case "whole":
      return t("farmHealth:area.whole");
    case "scattered":
      return t("farmHealth:area.scattered", { count: spots });
    case "centre":
      return t("farmHealth:area.centre");
    case "most":
      return name.direction
        ? t("farmHealth:area.most", { direction: t(`farmHealth:direction.${name.direction}`) })
        : t("farmHealth:area.mostPlain");
    case "direction":
    default:
      return name.direction ? t(`farmHealth:directionTitle.${name.direction}`) : "";
  }
}
