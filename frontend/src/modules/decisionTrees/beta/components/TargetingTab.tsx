// Which blocks a beta tree runs on: crops, countries, soil textures.
//
// The same three axes, and the same picker, as the classic editor's metadata
// panel. Each axis empty = any. The values live in the tree's definition
// (`crop_paths`, `country_codes`, `soil_textures`), so they are saved with the
// draft and take effect when that version is published: the catalogue row the
// sweep and the farm settings read follows the published version.
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Card } from "@/components/Card";
import { TreeTargetingPicker } from "@/modules/decisionTrees/components/TreeTargetingPicker";

import type { BetaTargeting } from "../lib/betaTree";

interface Props {
  targeting: BetaTargeting;
  readOnly: boolean;
  onChange: (next: BetaTargeting) => void;
}

function Summary({ label, values, any }: { label: string; values: string[]; any: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{label}</span>
      <span className="text-sm text-ap-ink">
        {values.length ? (
          <span className="font-mono text-xs">{values.join(", ")}</span>
        ) : (
          <span className="text-ap-muted">{any}</span>
        )}
      </span>
    </div>
  );
}

export function TargetingTab({ targeting, readOnly, onChange }: Props): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  const { t: tTrees } = useTranslation("decisionTrees");
  return (
    <Card title={t("designer.targeting.title")}>
      <p className="mb-4 text-xs text-ap-muted">{t("designer.targeting.intro")}</p>
      {readOnly ? (
        <div className="flex flex-col gap-3">
          <Summary
            label={tTrees("targeting.crop")}
            values={targeting.crop_paths}
            any={t("designer.targeting.any")}
          />
          <Summary
            label={tTrees("targeting.country")}
            values={targeting.country_codes}
            any={t("designer.targeting.any")}
          />
          <Summary
            label={tTrees("targeting.soil")}
            values={targeting.soil_textures.map((s) => tTrees(`targeting.soilValues.${s}`))}
            any={t("designer.targeting.any")}
          />
        </div>
      ) : (
        <TreeTargetingPicker
          cropPaths={targeting.crop_paths}
          countryCodes={targeting.country_codes}
          soilTextures={targeting.soil_textures}
          onCropPathsChange={(crop_paths) => onChange({ ...targeting, crop_paths })}
          onCountryCodesChange={(country_codes) => onChange({ ...targeting, country_codes })}
          onSoilTexturesChange={(soil_textures) => onChange({ ...targeting, soil_textures })}
        />
      )}
      <p className="mt-4 text-[11px] text-ap-muted">{t("designer.targeting.publishNote")}</p>
    </Card>
  );
}
