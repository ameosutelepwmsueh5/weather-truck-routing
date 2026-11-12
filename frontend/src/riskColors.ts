import type { RiskLevel } from "./types";

export const RISK_LEVELS: RiskLevel[] = ["LOW", "MODERATE", "HIGH", "SEVERE", "NO_TRAVEL"];

export const riskColors: Record<RiskLevel, string> = {
  LOW: "#16a34a",
  MODERATE: "#eab308",
  HIGH: "#f97316",
  SEVERE: "#dc2626",
  NO_TRAVEL: "#7f1d1d",
};

const STOPS: [number, number, number][] = [
  [22, 163, 74],
  [234, 179, 8],
  [249, 115, 22],
  [220, 38, 38],
  [127, 29, 29],
];

/** Smoothly interpolated RGB for a fractional risk score 0-4 (used by the heatmap). */
export function scoreToRgb(score: number): [number, number, number] {
  const s = Math.max(0, Math.min(4, score));
  const i = Math.min(3, Math.floor(s));
  const t = s - i;
  const a = STOPS[i];
  const b = STOPS[i + 1];
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

/**
 * Risk score at a fractional forecast hour, linearly blended between the two
 * neighbouring hourly scores (clamped to the available hours). Drives the smooth heatmap.
 */
export function blendScore(scores: number[], hour: number): number {
  if (!scores.length) return 0;
  const last = scores.length - 1;
  const h = Math.max(0, Math.min(hour, last));
  const lo = Math.floor(h);
  const hi = Math.min(lo + 1, last);
  return scores[lo] + (scores[hi] - scores[lo]) * (h - lo);
}

export const riskLabel = (r: string) => r.replace("_", " ");

/** Line colour per route, by its position in the (ranked) route list. Shared by map, cards and legend. */
const ROUTE_COLORS = ["#2453e6", "#7a3ff2", "#0b8aa8"];
export const routeColor = (index: number) => ROUTE_COLORS[index % ROUTE_COLORS.length];
