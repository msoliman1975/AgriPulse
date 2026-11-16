// Field photos on an activity, in the board's activity drawer (build plan 3.3).
//
// Staff with `plan.manage` can hide a single photo from investors (decision
// D5: photos reach the investor app automatically unless hidden). Everyone
// else who can read the board sees the photos and whether they are hidden.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActivityPhoto } from "@/api/plans";
import { useSetActivityPhotoHidden } from "@/queries/plans";

interface Props {
  activityId: string;
  farmId: string;
  photos: ActivityPhoto[];
  canManage: boolean;
}

export function ActivityPhotos({ activityId, farmId, photos, canManage }: Props): ReactNode {
  const { t } = useTranslation("board");
  const setHidden = useSetActivityPhotoHidden(farmId);
  const [failed, setFailed] = useState(false);

  if (photos.length === 0) return null;

  const toggle = (photo: ActivityPhoto): void => {
    setFailed(false);
    setHidden.mutate(
      { activityId, photoId: photo.id, hidden: !photo.hidden_from_investors },
      { onError: () => setFailed(true) },
    );
  };

  return (
    <div className="mt-3">
      <h4 className="text-xs font-medium text-ap-muted">{t("detail.photos")}</h4>
      <ul className="mt-1 grid grid-cols-3 gap-2">
        {photos.map((photo, index) => (
          <li key={photo.id} className="space-y-1">
            {photo.url ? (
              <a href={photo.url} target="_blank" rel="noreferrer">
                <img
                  src={photo.url}
                  alt={t("detail.photoAlt", { index: index + 1 })}
                  loading="lazy"
                  className={`aspect-square w-full rounded object-cover ${
                    photo.hidden_from_investors ? "opacity-60" : ""
                  }`}
                />
              </a>
            ) : (
              <div className="aspect-square w-full rounded bg-ap-line/40" />
            )}
            {canManage ? (
              <label className="flex items-center gap-1 text-[11px] text-ap-ink">
                <input
                  type="checkbox"
                  checked={photo.hidden_from_investors}
                  disabled={setHidden.isPending}
                  onChange={() => toggle(photo)}
                />
                {t("detail.hideFromInvestors")}
              </label>
            ) : photo.hidden_from_investors ? (
              <span className="text-[11px] text-ap-muted">{t("detail.hiddenFromInvestors")}</span>
            ) : null}
          </li>
        ))}
      </ul>
      {failed ? (
        <p role="alert" className="mt-1 text-xs text-ap-crit">
          {t("detail.photoToggleFailed")}
        </p>
      ) : null}
    </div>
  );
}
