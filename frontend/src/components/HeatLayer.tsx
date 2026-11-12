import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import type { HeatPoint } from "../types";
import { blendScore, scoreToRgb } from "../riskColors";

/**
 * Leaflet internals used to animate a custom canvas during zoom - the same ones
 * Leaflet's own ImageOverlay relies on (no public API exposes them).
 */
type LeafletMapInternals = L.Map & {
  _zoomAnimated?: boolean;
  _latLngBoundsToNewLayerBounds(bounds: L.LatLngBounds, zoom: number, center: L.LatLng): L.Bounds;
};

interface Props {
  points: HeatPoint[];
  /** Fractional hours after the forecast start. Scores are blended between neighbouring hours. */
  hour: number;
  /** Distance between sampled points; each glow is sized so neighbours overlap into a band. */
  spacingMiles?: number;
}

const METERS_PER_MILE = 1609.344;
/** Glow radius as a share of point spacing (> 0.5 so neighbouring glows overlap). */
const RADIUS_PER_SPACING = 0.8;
const MIN_RADIUS_MILES = 8;

/**
 * Lightweight canvas heatmap: one soft radial gradient per sampled corridor point,
 * coloured by the (interpolated) risk score at the chosen hour. Changing the hour
 * only repaints one canvas - no network calls and no React re-render of the map.
 * The canvas follows Leaflet's zoom animation (CSS transform) and is repainted
 * synchronously when the zoom settles, so it never lags behind the base map.
 */
export default function HeatLayer({ points, hour, spacingMiles = 25 }: Props) {
  const map = useMap();
  const latest = useRef({ points, hour, spacingMiles });
  latest.current = { points, hour, spacingMiles };
  const scheduleRef = useRef<() => void>(() => {});

  useEffect(() => {
    const pane = map.getPane("heatPane") ?? map.createPane("heatPane");
    pane.style.zIndex = "350";
    pane.style.pointerEvents = "none";
    const internals = map as LeafletMapInternals;
    const zoomAnimated = Boolean(internals._zoomAnimated);
    const canvas = L.DomUtil.create(
      "canvas",
      `heat-canvas ${zoomAnimated ? "leaflet-zoom-animated" : "leaflet-zoom-hide"}`,
      pane,
    ) as HTMLCanvasElement;
    let frame: number | null = null;
    let drawnBounds = map.getBounds(); // geographic area the canvas currently shows

    const draw = () => {
      if (frame != null) cancelAnimationFrame(frame);
      frame = null;
      const { points: pts, hour: h, spacingMiles: spacing } = latest.current;
      const size = map.getSize();
      const dpr = window.devicePixelRatio || 1;
      if (canvas.width !== size.x * dpr || canvas.height !== size.y * dpr) {
        canvas.width = size.x * dpr;
        canvas.height = size.y * dpr;
        canvas.style.width = `${size.x}px`;
        canvas.style.height = `${size.y}px`;
      }
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]));
      drawnBounds = L.latLngBounds(
        map.containerPointToLatLng([0, 0]),
        map.containerPointToLatLng([size.x, size.y]),
      );
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, size.x, size.y);

      const radiusMiles = Math.max(MIN_RADIUS_MILES, spacing * RADIUS_PER_SPACING);
      const visible = map.getBounds().pad(0.3);
      const zoomScale = Math.pow(2, map.getZoom());

      for (const p of pts) {
        if (!visible.contains([p.lat, p.lon])) continue;
        const score = blendScore(p.scores, h);
        const center = map.latLngToContainerPoint([p.lat, p.lon]);
        const metersPerPixel = (156543.03392 * Math.cos((p.lat * Math.PI) / 180)) / zoomScale;
        const radius = Math.max(10, (radiusMiles * METERS_PER_MILE) / metersPerPixel);
        const [r, g, bl] = scoreToRgb(score);
        const alpha = 0.28 + Math.min(score, 4) * 0.1; // worse weather = stronger glow
        const rgb = `${r | 0},${g | 0},${bl | 0}`;
        const grad = ctx.createRadialGradient(center.x, center.y, 0, center.x, center.y, radius);
        grad.addColorStop(0, `rgba(${rgb},${alpha})`);
        grad.addColorStop(0.5, `rgba(${rgb},${alpha * 0.6})`);
        grad.addColorStop(1, `rgba(${rgb},0)`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
        ctx.fill();
      }
    };

    const schedule = () => {
      if (frame == null) frame = requestAnimationFrame(draw);
    };

    // During a zoom animation, scale/translate the existing canvas exactly like
    // Leaflet's own overlays do, instead of leaving it stuck at the old scale.
    const onZoomAnim = (e: L.ZoomAnimEvent) => {
      const scale = map.getZoomScale(e.zoom);
      const offset = internals._latLngBoundsToNewLayerBounds(drawnBounds, e.zoom, e.center).min;
      if (!offset) return;
      L.DomUtil.setTransform(canvas, offset, scale);
    };

    scheduleRef.current = schedule;
    map.on("move", schedule); // panning: repaint on the next frame
    map.on("zoom zoomend viewreset resize", draw); // zoom settled: repaint immediately
    if (zoomAnimated) map.on("zoomanim", onZoomAnim);
    draw();

    return () => {
      map.off("move", schedule);
      map.off("zoom zoomend viewreset resize", draw);
      map.off("zoomanim", onZoomAnim);
      if (frame != null) cancelAnimationFrame(frame);
      scheduleRef.current = () => {};
      L.DomUtil.remove(canvas);
    };
  }, [map]);

  useEffect(() => {
    scheduleRef.current();
  }, [points, hour, spacingMiles]);

  return null;
}
