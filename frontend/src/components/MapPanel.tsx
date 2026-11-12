import { forwardRef, useState } from "react";
import type { AnalysisResult, Checkpoint } from "../types";
import HeatmapControl from "./HeatmapControl";
import RouteMap from "./RouteMap";

interface Props {
  result: AnalysisResult;
  selectedRouteId: string;
  onSelectRoute: (id: string) => void;
  focusedCheckpoint: Checkpoint | null;
}

/**
 * Owns the heatmap hour so dragging the slider only re-renders this subtree
 * (the route cards and checkpoint table elsewhere in the page are untouched).
 */
const MapPanel = forwardRef<HTMLDivElement, Props>(function MapPanel(
  { result, selectedRouteId, onSelectRoute, focusedCheckpoint },
  ref,
) {
  const [hour, setHour] = useState(0);
  const [showHeat, setShowHeat] = useState(true);
  return (
    <div className="map-panel panel" ref={ref}>
      <div className="panel-title">
        <div>
          <h3>Route map, checkpoints & weather heatmap</h3>
          <p>Click a route or checkpoint for details. Dots are colored by risk at the truck's ETA.</p>
        </div>
        <label className="toggle">
          <input type="checkbox" checked={showHeat} onChange={(e) => setShowHeat(e.target.checked)} /> Heatmap
        </label>
      </div>
      <HeatmapControl
        startTime={result.heatmap.start_time}
        maxHour={result.heatmap.hours ?? 48}
        hour={hour}
        onChange={setHour}
      />
      <RouteMap
        result={result}
        selectedRouteId={selectedRouteId}
        onSelectRoute={onSelectRoute}
        heatHour={hour}
        showHeat={showHeat}
        focusedCheckpoint={focusedCheckpoint}
      />
    </div>
  );
});

export default MapPanel;
