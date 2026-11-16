import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ActivityPhoto } from "@/api/plans";

const setActivityPhotoHidden = vi.fn();
vi.mock("@/api/plans", async (orig) => ({
  ...(await orig<typeof import("@/api/plans")>()),
  setActivityPhotoHidden: (...args: unknown[]) => setActivityPhotoHidden(...args),
}));

import { ActivityPhotos } from "./ActivityPhotos";

const photos: ActivityPhoto[] = [
  {
    id: "p1",
    url: "https://s3.test/p1.jpg",
    taken_at: null,
    created_at: "2026-11-16T05:00:00Z",
    created_by: null,
    hidden_from_investors: false,
  },
  {
    id: "p2",
    url: "https://s3.test/p2.jpg",
    taken_at: null,
    created_at: "2026-11-16T05:01:00Z",
    created_by: null,
    hidden_from_investors: true,
  },
];

function wrap(ui: ReactNode): ReactNode {
  return <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>;
}

describe("ActivityPhotos", () => {
  beforeEach(() => {
    setActivityPhotoHidden.mockReset().mockResolvedValue({});
  });

  it("renders nothing without photos", () => {
    const { container } = render(
      wrap(<ActivityPhotos activityId="a1" farmId="f1" photos={[]} canManage />),
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("lets a manager hide a photo from investors", async () => {
    render(wrap(<ActivityPhotos activityId="a1" farmId="f1" photos={photos} canManage />));
    expect(screen.getAllByRole("img")).toHaveLength(2);
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes[1]).toBeChecked();
    fireEvent.click(boxes[0]);
    await waitFor(() => expect(setActivityPhotoHidden).toHaveBeenCalledWith("a1", "p1", true));
  });

  it("shows others which photos are hidden, without a switch", () => {
    render(wrap(<ActivityPhotos activityId="a1" farmId="f1" photos={photos} canManage={false} />));
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByText("detail.hiddenFromInvestors")).toBeInTheDocument();
  });

  it("says so when the change fails", async () => {
    setActivityPhotoHidden.mockRejectedValue(new Error("nope"));
    render(wrap(<ActivityPhotos activityId="a1" farmId="f1" photos={photos} canManage />));
    fireEvent.click(screen.getAllByRole("checkbox")[0]);
    expect(await screen.findByRole("alert")).toHaveTextContent("detail.photoToggleFailed");
  });
});
