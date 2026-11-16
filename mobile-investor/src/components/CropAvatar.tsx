import { useState, type ReactNode } from "react";

/**
 * The crop's picture on a disc tinted with the stage colour. With no picture,
 * or when it fails to load (offline, older api), the crop's first letter.
 */
export function CropAvatar({
  src,
  name,
  color,
  size = 46,
}: {
  src: string | null | undefined;
  name: string;
  color: string;
  size?: number;
}): ReactNode {
  const [failed, setFailed] = useState(false);
  const letter = [...name.trim()][0] ?? "";
  return (
    <span
      className="crop-avatar"
      style={{ width: size, height: size, background: color }}
      aria-hidden
    >
      {src && !failed ? (
        <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} />
      ) : (
        <span className="crop-avatar-letter">{letter || "•"}</span>
      )}
    </span>
  );
}
