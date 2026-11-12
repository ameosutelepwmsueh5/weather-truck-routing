import { Clock3, MapPinned, ShieldCheck, AlertTriangle, Zap, CloudLightning, CloudRain } from "lucide-react";
import type { RouteOption } from "../types";
import { riskColors, riskLabel } from "../riskColors";
import { durationLabel, fmtMiles } from "../format";

interface Props {
  route: RouteOption;
  color: string;
  selected: boolean;
  onSelect: () => void;
}

/** Risk along the route: one segment per checkpoint, width = road miles it represents. */
function RiskStrip({ route }: { route: RouteOption }) {
  return (
    <>
      <div
        className="risk-strip"
        role="img"
        aria-label={`Risk along ${route.name}: worst ${riskLabel(route.summary.max_risk)}`}
      >
        {route.checkpoints.map((cp) => (
          <i
            key={cp.checkpoint_number}
            style={{ flexGrow: Math.max(cp.segment_miles, 0.01), background: riskColors[cp.risk_level] }}
            title={`Mile ${fmtMiles(cp.distance_miles)}: ${riskLabel(cp.risk_level)}`}
          />
        ))}
      </div>
      <div className="risk-strip-labels">
        <span>Start</span>
        <span>{route.summary.distance_miles} mi</span>
      </div>
    </>
  );
}

export default function RouteCard({ route, color, selected, onSelect }: Props) {
  const s = route.summary;
  return (
    <button
      className={`route-card ${selected ? "selected" : ""}`}
      onClick={onSelect}
      type="button"
      aria-pressed={selected}
    >
      <div className="route-card-top">
        <div>
          <div className="route-name">
            <span className="route-swatch" style={{ background: color }} aria-hidden />
            {route.name}
            {route.recommended && !route.blocked && <span className="recommended">RECOMMENDED</span>}
            {route.fastest && (
              <span className="fastest">
                <Zap size={10} /> FASTEST
              </span>
            )}
          </div>
          <div className="route-subtitle">
            Rank #{route.rank} · worst checkpoint: {riskLabel(s.max_risk)}
          </div>
        </div>
        {route.blocked ? (
          <span className="risk-pill no-travel">
            <AlertTriangle size={13} /> {s.no_travel_miles} mi No Travel
          </span>
        ) : (
          <span className="risk-pill safe">
            <ShieldCheck size={13} /> Drivable
          </span>
        )}
      </div>
      <RiskStrip route={route} />
      <div className="route-stats">
        <div>
          <MapPinned size={16} />
          <strong>{s.distance_miles} mi</strong>
          <small>Distance</small>
        </div>
        <div>
          <Clock3 size={16} />
          <strong>{durationLabel(s.duration_minutes)}</strong>
          <small>Truck time</small>
        </div>
        <div>
          <CloudLightning size={16} />
          <strong>{s.severe_miles} mi</strong>
          <small>Severe + No Travel</small>
        </div>
        <div>
          <CloudRain size={16} />
          <strong>{s.high_miles} mi</strong>
          <small>High risk</small>
        </div>
      </div>
      <div className="risk-score-row">
        <span>Average risk score</span>
        <strong>{s.average_risk_score.toFixed(2)} / 4</strong>
      </div>
    </button>
  );
}
