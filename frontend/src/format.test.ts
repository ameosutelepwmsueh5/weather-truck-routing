import { describe, expect, it } from "vitest";
import { durationLabel, fmtMiles, fmtRate } from "./format";

describe("fmtMiles", () => {
  it("shows at most one decimal", () => {
    expect(fmtMiles(185.72)).toBe("185.7");
    expect(fmtMiles(25)).toBe("25");
    expect(fmtMiles(0)).toBe("0");
  });
});

describe("durationLabel", () => {
  it("formats hours and zero-padded minutes", () => {
    expect(durationLabel(217)).toBe("3h 37m");
    expect(durationLabel(125)).toBe("2h 05m");
  });

  it("omits hours under one hour", () => {
    expect(durationLabel(45)).toBe("45m");
  });
});

describe("fmtRate", () => {
  it("shows two decimals", () => {
    expect(fmtRate(0.25)).toBe("0.25");
    expect(fmtRate(0)).toBe("0.00");
  });

  it("shows a trace that would round to zero as <0.01", () => {
    expect(fmtRate(0.004)).toBe("<0.01");
    expect(fmtRate(0.005)).toBe("0.01");
  });
});
