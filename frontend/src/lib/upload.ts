// Direct browser → S3 PUT for presigned uploads. We deliberately bypass
// `apiClient` because the axios interceptor would attach our Bearer JWT,
// which corrupts the S3 v4 signature. The presigned URL is the auth.

export class PresignedUploadError extends Error {
  public readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function uploadToPresignedUrl(
  file: File,
  url: string,
  headers: Record<string, string>,
): Promise<void> {
  const response = await fetch(url, { method: "PUT", body: file, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.text()) || detail;
    } catch {
      // body unreadable; keep status text
    }
    throw new PresignedUploadError(response.status, detail);
  }
}
