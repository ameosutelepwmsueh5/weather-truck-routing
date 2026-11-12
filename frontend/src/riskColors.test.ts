import { describe, expect, it } from "vitest";
import { blendScore, riskLabel, routeColor, scoreToRgb } from "./riskColors";

describe("blendScore (heatmap hour interpolation)", () => {
  const scores = [0, 2, 4, 1];

  it("returns the exact score on whole hours", () => {
    expect(blendScore(scores, 1)).toBe(2);
    expect(blendScore(scores, 3)).toBe(1);
  });

  it("blends linearly between neighbouring hours", () => {
    expect(blendScore(scores, 0.5)).toBe(1);
    expect(blendScore(scores, 1.25)).toBe(2.5);
    expect(blendScore(scores, 2.5)).toBe(2.5);
  });

  it("clamps outside the forecast range and handles empty input", () => {
    expect(blendScore(scores, -3)).toBe(0);
    expect(blendScore(scores, 99)).toBe(1);
    expect(blendScore([], 5)).toBe(0);
  });
});

describe("scoreToRgb", () => {
  it("maps the ends of the scale to Low green and No Travel dark red", () => {
    expect(scoreToRgb(0)).toEqual([22, 163, 74]);
    expect(scoreToRgb(4)).toEqual([127, 29, 29]);
  });

  it("interpolates between levels and clamps out-of-range scores", () => {
    const mid = scoreToRgb(0.5);
    expect(mid[0]).toBeCloseTo((22 + 234) / 2);
    expect(scoreToRgb(9)).toEqual(scoreToRgb(4));
    expect(scoreToRgb(-1)).toEqual(scoreToRgb(0));
  });
});

describe("labels and route colours", () => {
  it("formats risk levels for display", () => {
    expect(riskLabel("NO_TRAVEL")).toBe("NO TRAVEL");
  });

  it("gives each route a distinct colour and cycles after three", () => {
    expect(new Set([routeColor(0), routeColor(1), routeColor(2)]).size).toBe(3);
    expect(routeColor(3)).toBe(routeColor(0));
  });
});
