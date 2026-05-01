import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { setupTestI18n } from "@/i18n/testing";
import { AttachmentsTab } from "./AttachmentsTab";

function makeJwt(payload: object): string {
  return `${btoa(JSON.stringify({ alg: "none" }))}.${btoa(JSON.stringify(payload))}.sig`;
}

vi.mock("react-oidc-context", () => ({
  useAuth: () => ({
    user: { access_token: makeJwt({ tenant_role: "TenantAdmin" }) },
  }),
}));

const listFarmAttachmentsMock = vi.hoisted(() => vi.fn());
const listBlockAttachmentsMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/attachments", async () => {
  const actual = await vi.importActual<typeof import("@/api/attachments")>("@/api/attachments");
  return {
    ...actual,
    listFarmAttachments: listFarmAttachmentsMock,
    listBlockAttachments: listBlockAttachmentsMock,
    initFarmAttachment: vi.fn(),
    finalizeFarmAttachment: vi.fn(),
    deleteFarmAttachment: vi.fn(),
    initBlockAttachment: vi.fn(),
    finalizeBlockAttachment: vi.fn(),
    deleteBlockAttachment: vi.fn(),
  };
});

const FARM_ID = "11111111-1111-1111-1111-111111111111";

describe("AttachmentsTab", () => {
  beforeEach(() => {
    listFarmAttachmentsMock.mockReset();
    listBlockAttachmentsMock.mockReset();
  });

  it("renders the empty state in English (LTR)", async () => {
    listFarmAttachmentsMock.mockResolvedValue([]);
    await setupTestI18n("en");
    render(<AttachmentsTab ownerKind="farm" ownerId={FARM_ID} farmId={FARM_ID} />);
    await waitFor(() => expect(screen.getByText("No attachments yet.")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Attachments" })).toBeInTheDocument();
    // Upload form gated by capability — TenantAdmin grants attachment.write.
    expect(screen.getByLabelText("File")).toBeInTheDocument();
    expect(document.documentElement.getAttribute("dir")).toBe("ltr");
  });

  it("renders in Arabic (RTL)", async () => {
    listFarmAttachmentsMock.mockResolvedValue([]);
    await setupTestI18n("ar");
    render(<AttachmentsTab ownerKind="farm" ownerId={FARM_ID} farmId={FARM_ID} />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "المرفقات" })).toBeInTheDocument(),
    );
    expect(document.documentElement.getAttribute("dir")).toBe("rtl");
  });

  it("renders an existing attachment with localized kind and size", async () => {
    listFarmAttachmentsMock.mockResolvedValue([
      {
        id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        owner_kind: "farm",
        owner_id: FARM_ID,
        kind: "photo",
        s3_key: "tenants/x/farms/y/attachments/z/photo.jpg",
        original_filename: "photo.jpg",
        content_type: "image/jpeg",
        size_bytes: 2 * 1024 * 1024,
        caption: null,
        taken_at: null,
        geo_point: null,
        download_url: "https://example.com/photo.jpg?sig",
        download_url_expires_at: "2099-01-01T00:00:00Z",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    await setupTestI18n("en");
    render(<AttachmentsTab ownerKind="farm" ownerId={FARM_ID} farmId={FARM_ID} />);
    await waitFor(() => expect(screen.getByText("photo.jpg")).toBeInTheDocument());
    expect(screen.getByText(/Photo · 2\.0 MB/)).toBeInTheDocument();
    const img = screen.getByRole("img");
    expect(img.getAttribute("src")).toContain("photo.jpg");
  });

  it("uses the block API when ownerKind is 'block'", async () => {
    listBlockAttachmentsMock.mockResolvedValue([]);
    await setupTestI18n("en");
    render(<AttachmentsTab ownerKind="block" ownerId={FARM_ID} farmId={FARM_ID} />);
    await waitFor(() => expect(listBlockAttachmentsMock).toHaveBeenCalledWith(FARM_ID));
    expect(listFarmAttachmentsMock).not.toHaveBeenCalled();
  });
});
