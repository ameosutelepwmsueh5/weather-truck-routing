export function durationLabel(minutes: number) {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

/** Route mileage with at most one decimal (185.72 -> "185.7", 25 -> "25"). */
export const fmtMiles = (miles: number) => String(Math.round(miles * 10) / 10);

/** Precipitation rate with 2 decimals; a trace that would round to 0.00 shows as "<0.01". */
export function fmtRate(inchesPerHour: number) {
  return inchesPerHour > 0 && inchesPerHour < 0.005 ? "<0.01" : inchesPerHour.toFixed(2);
}

export const fmtEta = (iso: string) =>
  new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

export const fmtShortTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
