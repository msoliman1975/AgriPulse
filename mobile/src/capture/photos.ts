/**
 * Photos: shrink on the handset, then upload straight to object storage.
 *
 * The camera is reached with `<input type="file" accept="image/*"
 * capture="environment">` rather than a Capacitor plugin. Capacitor's
 * WebChromeClient already handles the file chooser and the camera permission,
 * so this needs no native code and no APK rebuild beyond the manifest entry.
 *
 * Shrinking is not a nicety. A modern handset writes 4–8 MB per frame; five of
 * those over a field connection is a scout standing still watching a progress
 * bar, and the server caps an attachment at 20 MB anyway. 1600 px on the long
 * edge is enough to see leaf spotting or a cracked emitter.
 */

import { initAttachmentUpload, initFlagPhotoUpload, uploadAttachment } from "@/api/client";

/** Long edge, in pixels, after shrinking. */
const MAX_EDGE = 1600;
/** JPEG quality. 0.8 is where further loss starts to show on leaf texture. */
const QUALITY = 0.8;
/** Agreed cap per capture. Five is a scout's account of one spot, not an album. */
export const MAX_PHOTOS = 5;

/**
 * Shrink to at most MAX_EDGE on the long side and re-encode as JPEG.
 *
 * Returns the original untouched if anything in the decode fails: a photo that
 * uploads large beats a photo that is lost, and the server cap is the backstop.
 */
export async function shrink(file: File): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    // Already small enough — re-encoding would only lose quality.
    if (scale === 1) return file;

    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", QUALITY),
    );
    return blob ?? file;
  } catch {
    return file;
  }
}

/**
 * Shrink, ask for a presigned PUT, upload, and hand back the storage key.
 *
 * The key is what goes on the observation. Nothing is written to the database
 * here on purpose: if the upload fails the scout is told and can retry, and no
 * observation row exists pointing at bytes that never arrived.
 */
export async function uploadPhoto(args: {
  file: File;
  farmId: string;
  signalDefinitionId: string;
}): Promise<string> {
  const blob = await shrink(args.file);
  const upload = await initAttachmentUpload({
    signal_definition_id: args.signalDefinitionId,
    farm_id: args.farmId,
    // The shrunk blob is always JPEG; the untouched fallback keeps its own type.
    content_type: blob.type || "image/jpeg",
    content_length: blob.size,
    filename: args.file.name || "photo.jpg",
  });
  await uploadAttachment(upload, blob);
  return upload.attachment_s3_key;
}

/**
 * The same shrink-then-PUT, for a photograph that belongs to a field flag
 * rather than to a signal.
 *
 * Split by the presign endpoint rather than by copying the pipeline: the
 * shrinking rules, the JPEG fallback and the "bytes first, row second" order
 * are the part that matters, and two copies of them would drift.
 */
export async function uploadFlagPhoto(args: { file: File; farmId: string }): Promise<string> {
  const blob = await shrink(args.file);
  const upload = await initFlagPhotoUpload({
    farm_id: args.farmId,
    content_type: blob.type || "image/jpeg",
    content_length: blob.size,
    filename: args.file.name || "photo.jpg",
  });
  await uploadAttachment(upload, blob);
  return upload.attachment_s3_key;
}
