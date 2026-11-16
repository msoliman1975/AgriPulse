import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Crop, CropVariety } from "@/api/crops";

const uploadCropImage = vi.fn();
const removeCropImage = vi.fn();
vi.mock("@/api/cropImages", async (orig) => ({
  ...(await orig<typeof import("@/api/cropImages")>()),
  uploadCropImage: (...args: unknown[]) => uploadCropImage(...args),
  removeCropImage: (...args: unknown[]) => removeCropImage(...args),
}));

import { CatalogImage } from "./CatalogImage";

const crop = {
  id: "crop-1",
  code: "mango",
  name_en: "Mango",
  name_ar: "مانجو",
  crop_image_url: "https://api.test/crops/1/256.webp",
} as Crop;
const variety = {
  id: "var-1",
  crop_id: "crop-1",
  code: "alphonso",
  name_en: "Alphonso",
  path: "mango.alphonso",
  crop_image_url: "https://api.test/crops/1/256.webp",
  has_own_image: false,
} as CropVariety;

function wrap(ui: ReactNode): ReactNode {
  return <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>;
}

describe("CatalogImage", () => {
  beforeEach(() => {
    uploadCropImage.mockReset().mockResolvedValue({});
    removeCropImage.mockReset().mockResolvedValue({});
  });

  it("uploads an accepted file for the crop", async () => {
    render(wrap(<CatalogImage chain={{ crop, variety: null, strain: null }} canManage />));
    const file = new File(["x"], "mango.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("catalog.image.upload"), {
      target: { files: [file] },
    });
    await waitFor(() => expect(uploadCropImage).toHaveBeenCalledWith("crop", "crop-1", file));
  });

  it("refuses a file of the wrong type without calling the API", () => {
    render(wrap(<CatalogImage chain={{ crop, variety: null, strain: null }} canManage />));
    fireEvent.change(screen.getByLabelText("catalog.image.upload"), {
      target: { files: [new File(["x"], "mango.gif", { type: "image/gif" })] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("catalog.image.imageType");
    expect(uploadCropImage).not.toHaveBeenCalled();
  });

  it("shows a variety the crop's picture as inherited, with no remove", () => {
    render(wrap(<CatalogImage chain={{ crop, variety, strain: null }} canManage />));
    expect(screen.getByText("catalog.image.inherited")).toBeInTheDocument();
    expect(screen.queryByText("catalog.image.useCrops")).not.toBeInTheDocument();
  });

  it("lets a variety drop its own picture", async () => {
    const own = { ...variety, has_own_image: true, crop_image_url: "https://api.test/v/256.webp" };
    render(wrap(<CatalogImage chain={{ crop, variety: own, strain: null }} canManage />));
    fireEvent.click(screen.getByText("catalog.image.useCrops"));
    await waitFor(() => expect(removeCropImage).toHaveBeenCalledWith("variety", "var-1"));
  });

  it("is read-only without the capability", () => {
    render(wrap(<CatalogImage chain={{ crop, variety: null, strain: null }} canManage={false} />));
    expect(screen.queryByText("catalog.image.replace")).not.toBeInTheDocument();
  });
});
