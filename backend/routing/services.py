"""Orchestrates one trip analysis. No Django imports, so it is easy to unit test."""
import os
from datetime import timedelta

from .geometry import sample_route, simplify
from .providers import (
    fetch_hourly_series, geocode_place, get_routes, hours_available_from, weather_at, weather_key,
)
from .risk_calculator import classify_checkpoint, rank_routes, summarize_route

TRUCK_AVG_MPH = float(os.environ.get("TRUCK_AVG_SPEED_MPH", "55"))
HEAT_SPACING_MILES = 25          # heatmap point spacing on normal trips
HEAT_MAX_POINTS_PER_ROUTE = 80   # long trips space points further apart (fewer weather calls)
HEAT_HOURS = 48

ROUTING_NOTICES = {
    "ors-hgv": "Routes come from OpenRouteService's truck (HGV) profile, which respects weight limits "
               "for this load; height, length and hazmat restrictions are not checked.",
    "osrm-car": "Routes come from the public OSRM car profile - truck restrictions (height, weight, hazmat) are NOT checked.",
}


def truck_duration_seconds(router_seconds, distance_miles, avg_mph=TRUCK_AVG_MPH):
    """Car routers use car speeds. Never assume a loaded truck averages faster than `avg_mph`."""
    return max(router_seconds, distance_miles / avg_mph * 3600)


def heat_spacing_miles(interval_miles, longest_route_miles):
    """
    Heatmap point spacing. When the checkpoints are dense enough they double as heatmap
    points (no extra weather calls); otherwise use ~25 mi, widened on very long trips so a
    route never needs more than HEAT_MAX_POINTS_PER_ROUTE extra forecast locations.
    """
    target = max(HEAT_SPACING_MILES, longest_route_miles / HEAT_MAX_POINTS_PER_ROUTE)
    return interval_miles if interval_miles <= target else target


def _checkpoint_key(sample):
    lon, lat = sample["coordinates"]
    return weather_key(lat, lon, precise=True)


def _grid_key(sample):
    lon, lat = sample["coordinates"]
    return weather_key(lat, lon)


def _floor_hour(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


def analyze(origin_text, destination_text, departure, load_weight_lb, interval_miles):
    origin = (
        origin_text
        if isinstance(origin_text, dict)
        else geocode_place(origin_text)
    )

    destination = (
        destination_text
        if isinstance(destination_text, dict)
        else geocode_place(destination_text)
    )
    raw_routes = get_routes(origin, destination, load_weight_lb=load_weight_lb)

    # 1) Sample every route (checkpoints at the chosen interval + heatmap points).
    #    Checkpoints drive the risk ranking, so they use their exact (~1 km) location;
    #    extra heatmap-only points use the coarse forecast grid to save API calls.
    heat_spacing = heat_spacing_miles(interval_miles, max(r["distance_miles"] for r in raw_routes))
    heat_is_checkpoints = heat_spacing == interval_miles
    heat_key = _checkpoint_key if heat_is_checkpoints else _grid_key
    plans = []
    all_keys = []
    for raw in raw_routes:
        checkpoints = sample_route(raw["coordinates"], interval_miles)
        heat_samples = checkpoints if heat_is_checkpoints else sample_route(raw["coordinates"], heat_spacing)
        plans.append((raw, checkpoints, heat_samples))
        all_keys += [_checkpoint_key(c) for c in checkpoints] + [heat_key(s) for s in heat_samples]

    # 2) One de-duplicated, batched weather lookup for everything.
    series_by_key = fetch_hourly_series(all_keys)

    # 3) Build routes: checkpoints get ETA-based weather + risk.
    routes, out_of_range = [], False
    heat_points = {}
    for index, (raw, checkpoints, heat_samples) in enumerate(plans):
        duration_s = truck_duration_seconds(raw["duration_seconds"], raw["distance_miles"])
        total_sampled = checkpoints[-1]["distance_miles"] or 1
        enriched = []
        for n, cp in enumerate(checkpoints, start=1):
            lat, lon = cp["coordinates"][1], cp["coordinates"][0]
            eta = departure + timedelta(seconds=duration_s * cp["distance_miles"] / total_sampled)
            weather = weather_at(series_by_key[_checkpoint_key(cp)], eta)
            out_of_range = out_of_range or weather.pop("out_of_range")
            risk = classify_checkpoint(
                weather["wind_mph"], weather["rain_in_per_hour"], weather["snow_in_per_hour"], load_weight_lb
            )
            enriched.append({**cp, **weather, **risk, "eta": eta.isoformat(), "checkpoint_number": n})

        routes.append({
            "id": f"route-{index + 1}",
            "name": f"Route {index + 1}",
            "geometry": simplify(raw["coordinates"]),
            "checkpoints": enriched,
            "summary": summarize_route(enriched, raw["distance_miles"], duration_s / 60),
        })
        for sample in heat_samples:
            lat, lon = sample["coordinates"][1], sample["coordinates"][0]
            heat_points.setdefault(heat_key(sample), (lat, lon))

    ranked, reason = rank_routes(routes)

    # 4) Heatmap: risk score for every hour 0..48 after departure at each sampled point.
    heat_start = _floor_hour(departure)
    heat, hours_ok = [], HEAT_HOURS + 1
    for key, (lat, lon) in heat_points.items():
        series = series_by_key[key]
        hours_ok = min(hours_ok, hours_available_from(series, heat_start))
        scores = []
        for h in range(HEAT_HOURS + 1):
            w = weather_at(series, heat_start + timedelta(hours=h))
            scores.append(classify_checkpoint(
                w["wind_mph"], w["rain_in_per_hour"], w["snow_in_per_hour"], load_weight_lb
            )["risk_score"])
        heat.append({"lat": round(lat, 4), "lon": round(lon, 4), "scores": scores})

    provider = raw_routes[0].get("provider", "osrm-car")
    notices = [
        ROUTING_NOTICES.get(provider, ROUTING_NOTICES["osrm-car"]),
        f"ETAs assume a truck average of at most {TRUCK_AVG_MPH:.0f} mph; weather uses the nearest forecast hour to each ETA.",
    ]
    if len(ranked) < 3:
        notices.append(f"Only {len(ranked)} distinct route(s) could be found for this trip.")
    if any(s.get("stale") for s in series_by_key.values()):
        notices.append("The weather service is rate limiting requests, so some forecasts are up to 3 hours old.")
    if out_of_range or hours_ok < HEAT_HOURS + 1:
        notices.append("Part of the trip or heatmap window is outside the forecast range; the nearest available hour was used.")

    return {
        "origin": origin,
        "destination": destination,
        "departure_time": departure.isoformat(),
        "load_weight_lb": load_weight_lb,
        "checkpoint_interval_miles": interval_miles,
        "routing_provider": provider,
        "routes": ranked,
        "recommendation": ranked[0]["id"],
        "recommendation_reason": reason,
        "all_routes_blocked": all(r["blocked"] for r in ranked),
        "heatmap": {
            "start_time": heat_start.isoformat(),
            "hours": HEAT_HOURS,
            "spacing_miles": round(heat_spacing, 1),
            "points": heat,
        },
        "notices": notices,
    }
