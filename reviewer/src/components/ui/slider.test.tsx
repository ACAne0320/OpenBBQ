import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Slider } from "./slider";

describe("Slider", () => {
  it("styles its horizontal track from Base UI's data-orientation attribute", () => {
    const { container } = render(<Slider value={[50]} aria-label="Zoom" />);
    const root = container.querySelector('[data-slot="slider"]');
    const control = container.querySelector('[data-slot="slider-control"]');
    const track = container.querySelector('[data-slot="slider-track"]');

    expect(root).toHaveClass("flex", "items-center");
    expect(control).toHaveClass("h-full", "items-center");
    expect(track).toHaveClass("data-[orientation=horizontal]:h-1");
    expect(track).toHaveClass("data-[orientation=horizontal]:w-full");
  });
});
