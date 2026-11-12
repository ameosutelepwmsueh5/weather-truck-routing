import { memo, useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Polyline, CircleMarker, Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import type { AnalysisResult, Checkpoint, RouteOption } from "../types";
import { riskColors, riskLabel, routeColor } from "../riskColors";
import { durationLabel, fmtMiles, fmtRate, fmtShortTime } from "../format";
import HeatLayer from "./HeatLayer";

/** Flies to the checkpoint picked in the table and rings it. */
function FocusCheckpoint({ checkpoint }: { checkpoint: Checkpoint | null }) {
  const map = useMap();
  const center = useMemo<[number, number] | null>(
    () => (checkpoint ? [checkpoint.coordinates[1], checkpoint.coordinates[0]] : null),
    [checkpoint],
  );
  useEffect(() => {
    if (center) map.flyTo(center, Math.max(map.getZoom(), 9), { duration: 0.8 });
  }, [center, map]);
  if (!center) return null;
  return (
    <CircleMarker
      center={center}
      radius={15}
      interactive={false}
      pathOptions={{ color: "#0f172a", weight: 3, fill: false, dashArray: "4 4" }}
    />
  );
}

const pin = (label: string, color: string) =>
  L.divIcon({
    className: "pin-icon",
    html: `<span style="background:${color}">${label}</span>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });

// Created once: a new icon object per render would make Leaflet call setIcon() on
// every slider frame.
const ORIGIN_ICON = pin("A", "#0d1321");
const DEST_ICON = pin("B", "#c4312b");

interface Props {
  result: AnalysisResult;
  selectedRouteId: string;
  onSelectRoute: (id: string) => void;
  heatHour: number;
  showHeat: boolean;
  focusedCheckpoint: Checkpoint | null;
}

/** Polylines are memoised so slider changes never rebuild route geometry. */
const RouteLines = memo(function RouteLines({
  routes,
  selectedId,
  onSelect,
}: {
  routes: RouteOption[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const paths = useMemo(
    () => routes.map((r) => r.geometry.map(([lon, lat]) => [lat, lon] as [number, number])),
    [routes],
  );
  // Draw the selected route last so it sits on top of overlapping alternatives.
  const order = useMemo(
    () =>
      routes
        .map((_, i) => i)
        .sort((a, b) => Number(routes[a].id === selectedId) - Number(routes[b].id === selectedId)),
    [routes, selectedId],
  );
  return (
    <>
      {order.map((i) => {
        const route = routes[i];
        const selected = route.id === selectedId;
        return (
          <Polyline
            key={`${route.id}-${selected ? "sel" : "alt"}`}
            positions={paths[i]}
            eventHandlers={{ click: () => onSelect(route.id) }}
            pathOptions={{ color: routeColor(i), weight: selected ? 7 : 4, opacity: selected ? 0.95 : 0.45 }}
          >
            <Popup>
              <strong>{route.name}</strong>
              {route.recommended ? " · recommended" : ""}
              <br />
              {route.summary.distance_miles} mi · {durationLabel(route.summary.duration_minutes)}
              <br />
              Severe + No Travel: {route.summary.severe_miles} mi · High: {route.summary.high_miles} mi
              <br />
              Avg risk {route.summary.average_risk_score.toFixed(2)} / 4
            </Popup>
          </Polyline>
        );
      })}
    </>
  );
});

const Checkpoints = memo(function Checkpoints({
  routes,
  selectedId,
}: {
  routes: RouteOption[];
  selectedId: string;
}) {
  return (
    <>
      {routes.flatMap((route, ri) =>
        route.checkpoints.map((cp) => {
          const selected = route.id === selectedId;
          return (
            <CircleMarker
              key={`${route.id}-${cp.checkpoint_number}`}
              center={[cp.coordinates[1], cp.coordinates[0]]}
              radius={selected ? 7 : 4}
              pathOptions={{
                color: selected ? "#fff" : routeColor(ri),
                weight: selected ? 2 : 1,
                fillColor: riskColors[cp.risk_level],
                fillOpacity: selected ? 0.95 : 0.6,
              }}
            >
              <Popup>
                <strong>
                  {route.name} · checkpoint {cp.checkpoint_number}
                </strong>
                <br />
                {fmtMiles(cp.distance_miles)} mi from start
                <br />
                ETA: {fmtShortTime(cp.eta)}
                <br />
                Risk: <strong>{riskLabel(cp.risk_level)}</strong>
                <br />
                Wind {cp.wind_mph.toFixed(1)} mph ({riskLabel(cp.wind_risk)})<br />
                Rain {fmtRate(cp.rain_in_per_hour)} in/hr ({riskLabel(cp.rain_risk)})<br />
                Snow {fmtRate(cp.snow_in_per_hour)} in/hr ({riskLabel(cp.snow_risk)})
              </Popup>
            </CircleMarker>
          );
        }),
      )}
    </>
  );
});

/**
 * Everything except the heat layer. Memoised so a playing heatmap (one render per
 * animation frame) never touches routes, checkpoints or markers.
 */
const StaticLayers = memo(function StaticLayers({
  result,
  selectedId,
  onSelect,
}: {
  result: AnalysisResult;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const { routes, origin, destination } = result;
  return (
    <>
      <RouteLines routes={routes} selectedId={selectedId} onSelect={onSelect} />
      <Checkpoints routes={routes} selectedId={selectedId} />
      <Marker position={[origin.lat, origin.lon]} icon={ORIGIN_ICON}>
        <Popup>{origin.display_name}</Popup>
      </Marker>
      <Marker position={[destination.lat, destination.lon]} icon={DEST_ICON}>
        <Popup>{destination.display_name}</Popup>
      </Marker>
    </>
  );
});

/** On-map key linking line colours to routes; also a quick way to switch routes. */
const RouteLegend = memo(function RouteLegend({
  routes,
  selectedId,
  onSelect,
}: {
  routes: RouteOption[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="map-route-legend" aria-label="Routes">
      {routes.map((r, i) => (
        <button
          key={r.id}
          type="button"
          className={r.id === selectedId ? "active" : ""}
          aria-pressed={r.id === selectedId}
          onClick={() => onSelect(r.id)}
        >
          <span className="route-swatch" style={{ background: routeColor(i) }} aria-hidden />
          <span>
            {r.name}
            {r.recommended && !r.blocked && <span className="legend-extra"> · recommended</span>}
          </span>
        </button>
      ))}
    </div>
  );
});

export default function RouteMap({
  result,
  selectedRouteId,
  onSelectRoute,
  heatHour,
  showHeat,
  focusedCheckpoint,
}: Props) {
  const { heatmap } = result;
  // Open directly on the routes (no throw-away tiles at a default view). The map
  // remounts for every new analysis, so this is the only fit needed.
  const bounds = useMemo(
    () =>
      L.latLngBounds(
        result.routes.flatMap((r) => r.geometry.map(([lon, lat]) => [lat, lon] as [number, number])),
      ),
    [result.routes],
  );
  return (
    <div className="map-wrap">
      <MapContainer
        bounds={bounds}
        boundsOptions={{ padding: [30, 30] }}
        zoomSnap={0.5}
        scrollWheelZoom
        preferCanvas
        className="route-map"
      >
        {/* Standard OSM tiles (no API key), desaturated via CSS on the tile pane only so
            route lines, risk dots and the heatmap carry the colour. */}
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />
        {showHeat && (
          <HeatLayer points={heatmap.points} hour={heatHour} spacingMiles={heatmap.spacing_miles} />
        )}
        <StaticLayers result={result} selectedId={selectedRouteId} onSelect={onSelectRoute} />
        <FocusCheckpoint checkpoint={focusedCheckpoint} />
      </MapContainer>
      <RouteLegend routes={result.routes} selectedId={selectedRouteId} onSelect={onSelectRoute} />
    </div>
  );
}
