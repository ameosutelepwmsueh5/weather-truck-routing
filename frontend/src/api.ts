import axios from "axios";
import type { AnalysisResult, TripInput } from "./types";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000",
  timeout: 180000,
});

export interface Place {
  display_name: string;
  lat: number;
  lon: number;
}

export async function searchPlaces(query: string): Promise<Place[]> {
  const response = await api.get("/api/places/", {
    params: { q: query },
  });

  return response.data.results;
}

export interface Health {
  status: string;
  routing: string;
  weather: string;
}

export async function getHealth(): Promise<Health> {
  const response = await api.get<Health>("/api/health/", { timeout: 15000 });
  return response.data;
}

export async function analyzeTrip(payload: TripInput) {
  const response = await api.post<AnalysisResult>("/api/analyze/", payload);

  return response.data;
}
