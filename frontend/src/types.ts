export type RiskLevel = "LOW" | "MODERATE" | "HIGH" | "SEVERE" | "NO_TRAVEL";

export interface Checkpoint {
  checkpoint_number: number;
  distance_miles: number;
  segment_miles: number;
  coordinates: [number, number]; // [lon, lat]
  eta: string;
  forecast_time: string;
  wind_mph: number;
  rain_in_per_hour: number;
  snow_in_per_hour: number;
  risk_level: RiskLevel;
  wind_risk: RiskLevel;
  rain_risk: RiskLevel;
  snow_risk: RiskLevel;
  risk_score: number;
}

export interface RouteSummary {
  severe_miles: number;
  no_travel_miles: number;
  high_miles: number;
  average_risk_score: number;
  duration_minutes: number;
  distance_miles: number;
  has_no_travel: boolean;
  max_risk: RiskLevel;
}

export interface RouteOption {
  id: string;
  name: string;
  rank: number;
  recommended: boolean;
  fastest: boolean;
  blocked: boolean;
  geometry: [number, number][];
  checkpoints: Checkpoint[];
  summary: RouteSummary;
}

export interface HeatPoint {
  lat: number;
  lon: number;
  scores: number[]; // risk score 0-4 for each hour 0..48 after start_time
}

export interface Heatmap {
  start_time: string;
  hours: number;
  spacing_miles: number; // distance between sampled points along each route
  points: HeatPoint[];
}

export interface AnalysisResult {
  routes: RouteOption[];
  recommendation: string | null;
  recommendation_reason: string;
  all_routes_blocked: boolean;
  heatmap: Heatmap;
  notices: string[];
  departure_time: string;
  load_weight_lb?: number;
  routing_provider?: "ors-hgv" | "osrm-car";
  checkpoint_interval_miles?: number;
  origin: { display_name: string; lat: number; lon: number };
  destination: { display_name: string; lat: number; lon: number };
}

export interface TripInput {
  origin: {
    display_name: string;
    lat: number;
    lon: number;
  };
  destination: {
    display_name: string;
    lat: number;
    lon: number;
  };
  departure_time: string;
  load_weight_lb: number;
  checkpoint_interval_miles: number;
}
