// The crop (or variety) picture in the catalog inspector, with upload and
// remove for curators (build plan 3.1).
//
// A variety without its own picture shows its crop's and says so; uploading
// one overrides the crop's for that variety only. Strains have no picture of
// their own: they show their variety's, which is the crop's when the variety
// has none.

import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import {
  CROP_IMAGE_TYPES,
  cropImageProblem,
  removeCropImage,
  uploadCropImage,
  type CropImageOwner,
} from "@/api/cropImages";
import { CropAvatar } from "@/components/CropAvatar";
import type { TaxonomyChain } from "@/modules/admin/lib/cropTaxonomy";

interface Props {
  chain: TaxonomyChain;
  canManage: boolean;
}

export function CatalogImage({ chain, canManage }: Props): ReactNode {
  const { t } = useTranslation("admin");
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Strains show their variety's picture and cannot change it here.
  const owner: CropImageOwner | null = chain.strain ? null : chain.variety ? "variety" : "crop";
  const node = chain.variety ?? chain.crop;
  const imageUrl = node.crop_image_url ?? chain.crop.crop_image_url ?? null;
  const ownsImage = chain.variety ? Boolean(chain.variety.has_own_image) : Boolean(imageUrl);
  const inherited = !ownsImage && Boolean(imageUrl);
  const name = chain.strain?.name_en ?? node.name_en;

  const run = async (action: () => Promise<unknown>): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await queryClient.invalidateQueries({ queryKey: ["cropCatalog"] });
    } catch {
      setError(t("catalog.image.failed"));
    } finally {
      setBusy(false);
    }
  };

  const onFile = (file: File | undefined): void => {
    if (!file || owner === null) return;
    const problem = cropImageProblem(file);
    if (problem) {
      setError(t(`catalog.image.${problem}`));
      return;
    }
    void run(() => uploadCropImage(owner, node.id, file));
  };

  return (
    <div className="flex items-center gap-3">
      <CropAvatar name={name} imageUrl={imageUrl} size="lg" />
      <div className="min-w-0 space-y-1 text-xs">
        <p className="text-ap-muted">
          {imageUrl
            ? inherited
              ? t("catalog.image.inherited")
              : t("catalog.image.own")
            : t("catalog.image.none")}
        </p>
        {canManage && owner !== null ? (
          <div className="flex flex-wrap gap-2">
            <input
              ref={input}
              type="file"
              accept={CROP_IMAGE_TYPES.join(",")}
              className="hidden"
              aria-label={t("catalog.image.upload")}
              onChange={(e) => {
                onFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              disabled={busy}
              onClick={() => input.current?.click()}
              className="rounded-md border border-ap-line bg-ap-panel px-2.5 py-1 text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
            >
              {busy
                ? t("catalog.image.uploading")
                : ownsImage
                  ? t("catalog.image.replace")
                  : t("catalog.image.upload")}
            </button>
            {ownsImage ? (
              <button
                type="button"
                disabled={busy}
                onClick={() => void run(() => removeCropImage(owner, node.id))}
                className="rounded-md border border-ap-line bg-ap-panel px-2.5 py-1 text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
              >
                {owner === "variety" ? t("catalog.image.useCrops") : t("catalog.image.remove")}
              </button>
            ) : null}
          </div>
        ) : null}
        {error ? (
          <p role="alert" className="text-ap-crit">
            {error}
          </p>
        ) : null}
        {canManage && owner !== null ? (
          <p className="text-[11px] text-ap-muted">{t("catalog.image.hint")}</p>
        ) : null}
      </div>
    </div>
  );
}
