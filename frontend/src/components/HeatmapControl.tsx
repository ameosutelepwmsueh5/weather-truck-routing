import { useEffect, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { RISK_LEVELS, riskColors, riskLabel } from "../riskColors";

interface Props {
  startTime: string;
  /** Last forecast hour available (48). */
  maxHour: number;
  /** Fractional hours after startTime. */
  hour: number;
  onChange: (hour: number) => void;
}

/** Playback speed: forecast hours per real second (0 -> 48 h in ~20 s). */
const HOURS_PER_SECOND = 2.4;

const fmt = new Intl.DateTimeFormat(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });

function offsetLabel(hour: number) {
  const totalMinutes = Math.round((hour * 60) / 10) * 10; // 10-minute resolution for the label
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  return m ? `+${h}h ${String(m).padStart(2, "0")}m` : `+${h}h`;
}

export default function HeatmapControl({ startTime, maxHour, hour, onChange }: Props) {
  const [playing, setPlaying] = useState(false);
  const hourRef = useRef(hour);
  hourRef.current = hour;

  // Continuous playback driven by requestAnimationFrame. The heat layer blends
  // between neighbouring forecast hours, so the colours glide instead of jumping.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const elapsed = Math.min(now - last, 100) / 1000; // clamp after a background-tab pause
      last = now;
      const next = hourRef.current + elapsed * HOURS_PER_SECOND;
      onChange(next >= maxHour ? 0 : next);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, onChange, maxHour]);

  const label = fmt.format(new Date(new Date(startTime).getTime() + hour * 3600_000));

  return (
    <div className="forecast-control">
      <label htmlFor="forecast">Weather heatmap · forecast hour</label>
      <strong>
        {label} ({offsetLabel(hour)})
      </strong>
      <div className="slider-row">
        <button
          type="button"
          className="play-button"
          onClick={() => setPlaying((p) => !p)}
          aria-label={playing ? "Pause animation" : "Play animation"}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        {/* step="any" gives continuous dragging; arrow keys still move one hour. */}
        <input
          id="forecast"
          type="range"
          min="0"
          max={maxHour}
          step="any"
          value={hour}
          aria-valuetext={`${label}, ${offsetLabel(hour)} after departure`}
          onChange={(e) => {
            setPlaying(false);
            onChange(Number(e.target.value));
          }}
        />
      </div>
      <div className="slider-labels">
        <span>Departure</span>
        <span>+{maxHour / 2}h</span>
        <span>+{maxHour}h</span>
      </div>
      <div className="heat-legend" aria-label="Heatmap legend">
        {RISK_LEVELS.map((r) => (
          <span key={r}>
            <i style={{ background: riskColors[r] }} />
            {riskLabel(r)}
          </span>
        ))}
      </div>
    </div>
  );
}
