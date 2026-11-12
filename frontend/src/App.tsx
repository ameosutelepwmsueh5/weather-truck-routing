import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isAxiosError } from "axios";
import { AlertCircle, AlertTriangle, CheckCircle2, Info, Truck } from "lucide-react";
import TripForm from "./components/TripForm";
import MapPanel from "./components/MapPanel";
import RouteCard from "./components/RouteCard";
import { analyzeTrip, getHealth, type Health } from "./api";
import { riskLabel, routeColor } from "./riskColors";
import { durationLabel, fmtEta, fmtMiles, fmtRate } from "./format";
import type { AnalysisResult, Checkpoint, RouteOption, TripInput } from "./types";

function errorMessage(err: unknown): string {
  if (isAxiosError<{ error?: string }>(err)) {
    if (err.response?.data?.error) return err.response.data.error;
    if (!err.response) return "Cannot reach the routing server. Check that the backend is running.";
  }
  return err instanceof Error ? err.message : "Unable to analyze this trip.";
}

/** Seconds since `active` became true (re-renders once a second while active). */
function useElapsedSeconds(active: boolean) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!active) return;
    setSeconds(0);
    const started = Date.now();
    const id = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return seconds;
}

const STEPS = [
  ["Search places", "Pick an origin and destination from the suggestions."],
  ["Set the trip", "Departure time, load weight and checkpoint spacing."],
  ["Compare routes", "Up to three routes scored on weather at the truck's ETA."],
];

export default function App() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [selectedRouteId, setSelectedRouteId] = useState("");
  const [focusedCheckpoint, setFocusedCheckpoint] = useState<Checkpoint | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const mapRef = useRef<HTMLDivElement>(null);
  const resultsRef = useRef<HTMLElement>(null);
  const elapsed = useElapsedSeconds(loading);
  // Which upstream services the backend is configured for (null = checking, "offline" = unreachable).
  const [health, setHealth] = useState<Health | "offline" | null>(null);
  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth("offline"));
  }, []);

  const selectedRoute = useMemo<RouteOption | undefined>(
    () => result?.routes.find((route) => route.id === selectedRouteId) || result?.routes[0],
    [result, selectedRouteId],
  );

  const selectRoute = useCallback((id: string) => {
    setSelectedRouteId(id);
    setFocusedCheckpoint(null);
  }, []);

  function focusCheckpoint(cp: Checkpoint) {
    setFocusedCheckpoint(cp);
    const map = mapRef.current;
    if (map && map.getBoundingClientRect().bottom < 120)
      map.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function handleAnalyze(values: TripInput) {
    setLoading(true);
    setError("");
    setResult(null);
    setFocusedCheckpoint(null);
    try {
      const data = await analyzeTrip(values);
      setResult(data);
      setSelectedRouteId(data.recommendation || data.routes[0]?.id || "");
      // On phones the results render below the form: bring them into view.
      if (window.matchMedia("(max-width: 760px)").matches) {
        requestAnimationFrame(() =>
          resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
        );
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  const best = result?.routes[0];

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <Truck size={18} strokeWidth={2.2} />
          </div>
          <strong>RouteWise</strong>
          <span className="brand-divider" aria-hidden />
          <span className="brand-sub">Weather-aware truck routing</span>
        </div>
        <div className="topbar-meta">
          {health === "offline" ? (
            <span className="source-chip offline">
              <i /> API offline
            </span>
          ) : (
            <>
              <span className="source-chip">
                <i /> Routing · {health?.routing ?? "…"}
              </span>
              <span className="source-chip">
                <i /> Weather · {health?.weather ?? "…"}
              </span>
            </>
          )}
        </div>
      </header>

      <main className="workspace">
        <aside className="sidebar">
          <TripForm onSubmit={handleAnalyze} loading={loading} />
          <div className="info-note">
            <Info size={15} />
            <span>
              Prototype: truck weight limits are checked only when truck routing (OpenRouteService) is
              enabled; height and hazmat restrictions are not. See the notes under each result.
            </span>
          </div>
        </aside>

        <section className="main-content" aria-live="polite" ref={resultsRef}>
          {error && (
            <div className="error-banner" role="alert">
              <AlertCircle size={18} />
              {error}
            </div>
          )}

          {!result && !loading && (
            <div className="empty-state panel">
              <span className="eyebrow-label">Route risk analysis</span>
              <h1>Choose the safest route before the truck leaves the yard.</h1>
              <p>
                Routes are scored on forecast wind, rain and snow at the moment the truck reaches each
                checkpoint, adjusted for load weight.
              </p>
              <ol className="steps">
                {STEPS.map(([title, text], i) => (
                  <li key={title}>
                    <span className="step-num">{String(i + 1).padStart(2, "0")}</span>
                    <div>
                      <strong>{title}</strong>
                      <p>{text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {loading && (
            <div className="loading-panel panel">
              <span className="large-spinner" />
              <h2>
                Analyzing your trip <span className="elapsed">{elapsed}s</span>
              </h2>
              <p>
                Finding up to three routes, then loading the forecast at every checkpoint for the truck's
                arrival time.
              </p>
              <p className="loading-hint">
                {elapsed < 12
                  ? "Usually 5–15 seconds."
                  : "Long trips need many forecasts, so this can take up to a minute."}
              </p>
            </div>
          )}

          {result && best && (
            <>
              <section className={`decision panel ${result.all_routes_blocked ? "blocked" : ""}`}>
                <div className="decision-head">
                  <span className="eyebrow-label">
                    {result.all_routes_blocked ? (
                      <>
                        <AlertTriangle size={13} /> Do not depart as planned
                      </>
                    ) : (
                      <>
                        <CheckCircle2 size={13} /> Recommended route
                      </>
                    )}
                  </span>
                  <h2>
                    <span className="route-swatch" style={{ background: routeColor(0) }} aria-hidden />
                    {best.name}
                  </h2>
                  <p>{result.recommendation_reason}</p>
                </div>
                <dl className="metric-grid">
                  <div>
                    <dt>Distance</dt>
                    <dd>
                      {best.summary.distance_miles}
                      <small>mi</small>
                    </dd>
                  </div>
                  <div>
                    <dt>Truck time</dt>
                    <dd>{durationLabel(best.summary.duration_minutes)}</dd>
                  </div>
                  <div>
                    <dt>Severe + No Travel</dt>
                    <dd>
                      {best.summary.severe_miles}
                      <small>mi</small>
                    </dd>
                  </div>
                  <div>
                    <dt>High risk</dt>
                    <dd>
                      {best.summary.high_miles}
                      <small>mi</small>
                    </dd>
                  </div>
                  <div>
                    <dt>Avg risk</dt>
                    <dd>
                      {best.summary.average_risk_score.toFixed(2)}
                      <small>/ 4</small>
                    </dd>
                  </div>
                </dl>
              </section>

              <div className="trip-strip panel">
                <div>
                  <small>Origin</small>
                  <strong title={result.origin.display_name}>{result.origin.display_name}</strong>
                </div>
                <div>
                  <small>Destination</small>
                  <strong title={result.destination.display_name}>{result.destination.display_name}</strong>
                </div>
                <div>
                  <small>Departure</small>
                  <strong>{fmtEta(result.departure_time)}</strong>
                </div>
                {result.load_weight_lb != null && (
                  <div>
                    <small>Load</small>
                    <strong>{result.load_weight_lb.toLocaleString()} lb</strong>
                  </div>
                )}
              </div>

              <MapPanel
                ref={mapRef}
                result={result}
                selectedRouteId={selectedRoute?.id ?? ""}
                onSelectRoute={selectRoute}
                focusedCheckpoint={focusedCheckpoint}
              />

              <div className="section-head">
                <h3>
                  Routes <span className="count">{result.routes.length}</span>
                </h3>
                <span>Ranked by No Travel → Severe → High miles → avg risk (±0.05) → time</span>
              </div>
              <div className="route-list">
                {result.routes.map((route, i) => (
                  <RouteCard
                    key={route.id}
                    route={route}
                    color={routeColor(i)}
                    selected={route.id === selectedRoute?.id}
                    onSelect={() => selectRoute(route.id)}
                  />
                ))}
              </div>

              {selectedRoute && (
                <div className="checkpoint-panel panel">
                  <div className="panel-title">
                    <div>
                      <h3>{selectedRoute.name} · checkpoints</h3>
                      <p>Weather at the truck's estimated arrival. Select a row to locate it on the map.</p>
                    </div>
                    <span className="route-count">{selectedRoute.checkpoints.length} points</span>
                  </div>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Mile</th>
                          <th>ETA</th>
                          <th>Wind</th>
                          <th>Rain</th>
                          <th>Snow</th>
                          <th>Risk</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedRoute.checkpoints.map((cp) => (
                          <tr
                            key={cp.checkpoint_number}
                            tabIndex={0}
                            className={focusedCheckpoint === cp ? "focused" : undefined}
                            onClick={() => focusCheckpoint(cp)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                focusCheckpoint(cp);
                              }
                            }}
                          >
                            <td className="num">{fmtMiles(cp.distance_miles)}</td>
                            <td>{fmtEta(cp.eta)}</td>
                            <td className="num">
                              {cp.wind_mph.toFixed(1)} <small>mph</small>
                            </td>
                            <td className="num">
                              {fmtRate(cp.rain_in_per_hour)} <small>in/h</small>
                            </td>
                            <td className="num">
                              {fmtRate(cp.snow_in_per_hour)} <small>in/h</small>
                            </td>
                            <td>
                              <span className={`risk-tag ${cp.risk_level.toLowerCase()}`}>
                                {riskLabel(cp.risk_level)}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <div className="notice-list">
                {result.notices.map((note) => (
                  <p key={note}>
                    <Info size={14} />
                    {note}
                  </p>
                ))}
              </div>
            </>
          )}
        </section>
      </main>
      <footer>
        RouteWise · Assessment prototype · Verify road restrictions and official weather advisories before
        dispatch.
      </footer>
    </div>
  );
}
