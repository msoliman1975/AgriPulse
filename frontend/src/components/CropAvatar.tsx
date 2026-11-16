// A crop's picture as a round avatar, with a lettered fallback.
//
// The image comes from a public, cacheable URL (`crop_icon_url` /
// `crop_image_url` on catalogue, block-crop and board rows). Until a crop has
// an image — or while the worker is still writing its renditions, or if the
// image fails to load — the avatar is a coloured circle with the crop's
// first letter, the colour picked from the name so a crop keeps its colour.

import { useState, type ReactNode } from "react";

const SIZES = {
  xs: "h-5 w-5 text-[10px]",
  sm: "h-7 w-7 text-xs",
  md: "h-10 w-10 text-sm",
  lg: "h-16 w-16 text-xl",
} as const;

export type CropAvatarSize = keyof typeof SIZES;

// Soft backgrounds that read in both themes, with ink that passes contrast.
const PALETTE = [
  "bg-emerald-100 text-emerald-800",
  "bg-amber-100 text-amber-800",
  "bg-sky-100 text-sky-800",
  "bg-rose-100 text-rose-800",
  "bg-lime-100 text-lime-800",
  "bg-violet-100 text-violet-800",
  "bg-orange-100 text-orange-800",
  "bg-teal-100 text-teal-800",
] as const;

/** Stable palette slot for a name. */
export function avatarColor(name: string): string {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

/** The first letter of the name (whole grapheme for Arabic), upper-cased. */
export function avatarLetter(name: string): string {
  const first = Array.from(name.trim())[0];
  return first ? first.toLocaleUpperCase() : "?";
}

interface Props {
  /** Shown as the fallback letter and the image's alt text. */
  name: string;
  imageUrl?: string | null;
  size?: CropAvatarSize;
  className?: string;
}

export function CropAvatar({ name, imageUrl, size = "sm", className = "" }: Props): ReactNode {
  // Remember which URL failed, so a new URL (a re-upload) gets its own try.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage = Boolean(imageUrl) && failedUrl !== imageUrl;
  const base = `inline-flex flex-shrink-0 items-center justify-center overflow-hidden rounded-full ${SIZES[size]} ${className}`;

  if (showImage) {
    return (
      <img
        src={imageUrl as string}
        alt={name}
        loading="lazy"
        decoding="async"
        onError={() => setFailedUrl(imageUrl ?? null)}
        className={`${base} object-cover`}
      />
    );
  }
  return (
    <span
      role="img"
      aria-label={name}
      data-testid="crop-avatar-fallback"
      className={`${base} font-semibold ${avatarColor(name)}`}
    >
      {avatarLetter(name)}
    </span>
  );
}
