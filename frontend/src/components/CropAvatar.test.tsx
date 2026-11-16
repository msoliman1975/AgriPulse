import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CropAvatar, avatarColor, avatarLetter } from "./CropAvatar";

describe("CropAvatar", () => {
  it("shows the image when there is one", () => {
    render(<CropAvatar name="Date palm" imageUrl="https://api.test/x/64.webp" />);
    const img = screen.getByRole("img", { name: "Date palm" });
    expect(img.tagName).toBe("IMG");
    expect(img).toHaveAttribute("src", "https://api.test/x/64.webp");
  });

  it("falls back to the first letter without an image", () => {
    render(<CropAvatar name="mango" imageUrl={null} />);
    const fallback = screen.getByTestId("crop-avatar-fallback");
    expect(fallback).toHaveTextContent("M");
    expect(fallback).toHaveAccessibleName("mango");
  });

  it("falls back when the image fails, and retries a new URL", () => {
    const { rerender } = render(<CropAvatar name="Olive" imageUrl="https://api.test/a.webp" />);
    fireEvent.error(screen.getByRole("img", { name: "Olive" }));
    expect(screen.getByTestId("crop-avatar-fallback")).toHaveTextContent("O");

    rerender(<CropAvatar name="Olive" imageUrl="https://api.test/b.webp" />);
    expect(screen.getByRole("img", { name: "Olive" }).tagName).toBe("IMG");
  });

  it("uses the Arabic letter and a stable colour", () => {
    expect(avatarLetter("  نخيل")).toBe("ن");
    expect(avatarLetter("")).toBe("?");
    expect(avatarColor("Mango")).toBe(avatarColor("Mango"));
  });
});
