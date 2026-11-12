"""Third-party integrations: Photon (place autocomplete), Nominatim (geocoding), OSRM (routing), Open-Meteo (weather)."""
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import requests

from .geometry import cumulative_miles, haversine_miles, mean_separation_miles, point_at_distance

logger = logging.getLogger(__name__)

USER_AGENT = "WeatherAwareTruckRouting/2.0 (assessment project)"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
# Optional truck-aware routing. With ORS_API_KEY set (free key at openrouteservice.org),
# routes come from OpenRouteService's heavy-goods-vehicle profile, which honours truck
# weight limits and uses truck speeds; without it (or if ORS fails) OSRM's car profile.
ORS_API_KEY = os.environ.get("ORS_API_KEY", "").strip()
ORS_URL = "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"
ORS_MAX_ALTERNATIVES_MILES = 60  # ORS computes alternative routes only for short trips (~100 km)
# The brief's "load weight" is cargo; weight limits apply to the whole vehicle.
TRUCK_EMPTY_WEIGHT_LB = float(os.environ.get("TRUCK_EMPTY_WEIGHT_LB", "35000"))
LB_PER_TONNE = 2204.62
# Free tier by default. With OPEN_METEO_API_KEY set, the commercial endpoint (no shared
# free-tier limits) is used instead.
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "").strip()
OPEN_METEO_URL = (
    "https://customer-api.open-meteo.com/v1/forecast" if OPEN_METEO_API_KEY
    else "https://api.open-meteo.com/v1/forecast"
)
METERS_PER_MILE = 1609.344
WEATHER_CHUNK = 40          # coordinates per Open-Meteo request
WEATHER_CACHE_TTL = 15 * 60  # seconds a forecast counts as fresh
WEATHER_STALE_MAX = 3 * 3600  # older forecasts may still stand in when rate-limited; evicted after this
WEATHER_GRID_DEG = 0.1       # forecast locations are snapped to this grid (see weather_key)
WEATHER_WORKERS = 2         # parallel Open-Meteo requests (more just hits the rate limit sooner)
RATE_LIMIT_MAX_WAIT = 12     # seconds to wait per 429 retry (Retry-After is honoured up to this)
PAST_DAYS = 1
FORECAST_DAYS = 7


class ProviderError(Exception):
    """An upstream service failed or returned nothing useful (maps to HTTP 502)."""


class RateLimitedError(ProviderError):
    """An upstream service is rate limiting us (maps to HTTP 503 + Retry-After)."""


class NoRouteError(ProviderError):
    """The trip itself is impossible, e.g. no road connects the places (maps to HTTP 422)."""


_OSRM_NO_ROUTE_CODES = {
    "NoRoute": "No drivable road connects these places (they may be on different continents or islands).",
    "NoSegment": "No road was found near the origin or destination.",
    "NoMatch": "No road was found near the origin or destination.",
}

# Geocoding is limited to these ISO country codes (the app's rules and units are
# North American). Set GEOCODE_COUNTRIES="" to search worldwide.
GEOCODE_COUNTRIES = os.environ.get("GEOCODE_COUNTRIES", "us,ca,mx").strip()


def _nominatim_params(query, limit, **extra):
    params = {"q": query, "format": "jsonv2", "limit": limit, **extra}
    if GEOCODE_COUNTRIES:
        params["countrycodes"] = GEOCODE_COUNTRIES
    return params


# --------------------------------------------------------------------------- geocoding
@lru_cache(maxsize=256)
def _geocode_cached(place: str):
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=_nominatim_params(place, 1),
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
        results = response.json()
    except requests.RequestException as exc:
        raise ProviderError(f"Geocoding service error: {exc}") from exc
    if not results:
        where = f" in {GEOCODE_COUNTRIES.upper()}" if GEOCODE_COUNTRIES else ""
        raise NoRouteError(f"Could not find location{where}: {place}")
    item = results[0]
    return (float(item["lat"]), float(item["lon"]), item.get("display_name", place))


def geocode_place(place: str):
    lat, lon, name = _geocode_cached(place.strip().lower())
    return {"lat": lat, "lon": lon, "display_name": name}


PHOTON_URL = "https://photon.komoot.io/api/"
_ALLOWED_COUNTRIES = {c.strip().upper() for c in GEOCODE_COUNTRIES.split(",") if c.strip()}
# Bias Photon to North America when only US/CA/MX are allowed (results are filtered anyway).
_PHOTON_BBOX = "-170,14,-50,72" if _ALLOWED_COUNTRIES and _ALLOWED_COUNTRIES <= {"US", "CA", "MX"} else None


def _photon_label(props):
    """'Indianapolis, Indiana, United States' style label from Photon properties."""
    street = " ".join(p for p in (props.get("housenumber"), props.get("street")) if p)
    parts = [props.get("name") or street, street if props.get("name") else None,
             props.get("city"), props.get("state"), props.get("country")]
    label = []
    for part in parts:
        if part and part not in label:
            label.append(part)
    return ", ".join(label)


@lru_cache(maxsize=512)
def _search_places_cached(query):
    params = {"q": query, "limit": 15, "lang": "en"}
    if _PHOTON_BBOX:
        params["bbox"] = _PHOTON_BBOX
    try:
        response = requests.get(PHOTON_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
        response.raise_for_status()
        features = response.json().get("features", [])
    except (requests.RequestException, ValueError) as exc:
        raise ProviderError(f"Place search error: {exc}") from exc

    results = []
    for f in features:
        props = f.get("properties") or {}
        if _ALLOWED_COUNTRIES and (props.get("countrycode") or "").upper() not in _ALLOWED_COUNTRIES:
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        label = _photon_label(props)
        if label and all(label != r[0] for r in results):
            results.append((label, float(lat), float(lon)))
        if len(results) == 5:
            break
    return tuple(results)


def search_places(query):
    """
    Search-as-you-type place suggestions (up to 5) via Photon, an OpenStreetMap
    geocoder built for autocomplete. Nominatim's usage policy forbids autocomplete
    on its public server, so Nominatim is only used for one-off lookups.
    """
    query = " ".join(query.split())
    if len(query) < 3:
        return []
    return [{"display_name": label, "lat": lat, "lon": lon}
            for label, lat, lon in _search_places_cached(query.lower())]



# --------------------------------------------------------------------------- routing
def _osrm(coords_param, **extra):
    params = {"steps": "false", "overview": "full", "geometries": "geojson"}
    params.update(extra)
    try:
        response = requests.get(
            OSRM_URL + coords_param, params=params,
            headers={"User-Agent": USER_AGENT}, timeout=30,
        )
    except requests.RequestException as exc:
        raise ProviderError(f"Routing service error: {exc}") from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    code = data.get("code")
    # OSRM reports "no road between these points" as HTTP 400 with a JSON code;
    # surface that as a user-facing problem instead of a raw "400 Bad Request".
    if code in _OSRM_NO_ROUTE_CODES:
        raise NoRouteError(_OSRM_NO_ROUTE_CODES[code])
    if not response.ok:
        raise ProviderError(f"Routing service error: HTTP {response.status_code} {data.get('message', '')}".strip())
    if code != "Ok" or not data.get("routes"):
        return []
    return data["routes"]


def _normalize(osrm_route):
    return {
        "coordinates": osrm_route["geometry"]["coordinates"],
        "distance_miles": float(osrm_route["distance"]) / METERS_PER_MILE,
        "duration_seconds": float(osrm_route["duration"]),
    }


_ORS_NO_ROUTE_CODES = {
    2009: _OSRM_NO_ROUTE_CODES["NoRoute"],     # route could not be found
    2010: _OSRM_NO_ROUTE_CODES["NoSegment"],   # point not near a routable road
}


def _ors(points, alternatives, load_weight_lb):
    """OpenRouteService HGV routes between [lon, lat] points, normalised like OSRM's."""
    gross_tonnes = (load_weight_lb + TRUCK_EMPTY_WEIGHT_LB) / LB_PER_TONNE
    body = {
        "coordinates": [[round(lon, 6), round(lat, 6)] for lon, lat in points],
        "radiuses": [-1] * len(points),  # snap to the nearest road however far (via points may be off-road)
        "instructions": False,
        "options": {"vehicle_type": "hgv",
                    "profile_params": {"restrictions": {"weight": round(gross_tonnes, 1)}}},
    }
    if alternatives:
        body["alternative_routes"] = {"target_count": 3, "share_factor": 0.6, "weight_factor": 1.6}
    try:
        response = requests.post(ORS_URL, json=body, timeout=30,
                                 headers={"Authorization": ORS_API_KEY, "User-Agent": USER_AGENT})
    except requests.RequestException as exc:
        raise ProviderError(f"Truck routing service error: {exc}") from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        if error.get("code") in _ORS_NO_ROUTE_CODES:
            raise NoRouteError(_ORS_NO_ROUTE_CODES[error["code"]])
        raise ProviderError(f"Truck routing service error: HTTP {response.status_code} {error.get('message', '')}".strip())
    routes = []
    for feature in data.get("features", []):
        summary = (feature.get("properties") or {}).get("summary") or {}
        routes.append({
            "coordinates": feature["geometry"]["coordinates"],
            "distance_miles": float(summary.get("distance", 0)) / METERS_PER_MILE,
            "duration_seconds": float(summary.get("duration", 0)),
        })
    return routes


def _fetch_routes(provider, points, alternatives, load_weight_lb):
    """Normalised routes through [lon, lat] `points` from the chosen provider."""
    if provider == "ors-hgv":
        return _ors(points, alternatives, load_weight_lb)
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in points)
    return [_normalize(r) for r in _osrm(coords, alternatives="3" if alternatives else "false")]


def _is_distinct(candidate, existing, min_separation_miles=1.5):
    return all(
        mean_separation_miles(candidate["coordinates"], other["coordinates"]) > min_separation_miles
        for other in existing
    )


def _via_point(base, fraction, offset_share, side):
    """
    A point `fraction` of the way along `base`, pushed sideways (perpendicular to the
    road's *local* direction there) by `offset_share` of the route length.
    """
    coords = base["coordinates"]
    cumulative = cumulative_miles(coords)
    total = cumulative[-1]
    d = total * fraction
    anchor = point_at_distance(coords, cumulative, d)
    behind = point_at_distance(coords, cumulative, max(0.0, d - 10))
    ahead = point_at_distance(coords, cumulative, min(total, d + 10))
    cos_lat = max(math.cos(math.radians(anchor[1])), 0.2)
    dx = (ahead[0] - behind[0]) * cos_lat * 69.0
    dy = (ahead[1] - behind[1]) * 69.0
    norm = math.hypot(dx, dy)
    if norm == 0:  # degenerate geometry: fall back to the overall trip direction
        dx = (coords[-1][0] - coords[0][0]) * cos_lat * 69.0
        dy = (coords[-1][1] - coords[0][1]) * 69.0
        norm = math.hypot(dx, dy) or 1.0
    offset = max(6.0, base["distance_miles"] * offset_share)
    px, py = (-dy / norm) * side * offset, (dx / norm) * side * offset
    return [anchor[0] + px / (69.0 * cos_lat), anchor[1] + py / 69.0]


# Rounds of via-point attempts, tried in order until enough routes exist:
# (fraction along the main route, sideways offset as a share of its length).
# Each entry is tried on both sides; a round's requests run in parallel.
VIA_ROUNDS = [
    [(0.5, 0.18)],
    [(0.33, 0.15), (0.67, 0.15)],
    [(0.5, 0.35)],
]
MAX_DETOUR_FACTOR = 1.5  # reject candidates longer than 1.5x the main route (+10 mi)


def _route_via(provider, ends, via, load_weight_lb):
    try:
        found = _fetch_routes(provider, [ends[0], via, ends[1]], False, load_weight_lb)
    except ProviderError:
        return None  # an extra candidate failing must not fail the whole analysis
    return found[0] if found else None


def _base_routes(provider, ends, load_weight_lb):
    # ORS only offers alternatives for short trips; longer ones rely on the via-point rounds.
    alternatives = provider != "ors-hgv" or haversine_miles(*ends) <= ORS_MAX_ALTERNATIVES_MILES
    return _fetch_routes(provider, ends, alternatives, load_weight_lb)


def get_routes(origin, destination, wanted=3, load_weight_lb=0):
    """
    Up to `wanted` distinct driving routes, each tagged with its `provider`:
    "ors-hgv" (truck profile, when ORS_API_KEY is set) or "osrm-car". The provider's
    own alternatives come first; if it returns fewer, extra candidates are requested
    by forcing via-points beside the main route (several positions/offsets, both
    sides) and keeping only genuinely different, non-absurd detours - shortest first.
    If the truck router fails for a reason other than "no route", OSRM is used instead.
    """
    ends = [[origin["lon"], origin["lat"]], [destination["lon"], destination["lat"]]]
    provider = "ors-hgv" if ORS_API_KEY else "osrm-car"
    try:
        try:
            raw = _base_routes(provider, ends, load_weight_lb)
        except NoRouteError:
            raise
        except ProviderError as exc:
            if provider != "ors-hgv":
                raise
            logger.warning("Truck routing failed (%s); falling back to OSRM.", exc)
            provider = "osrm-car"
            raw = _base_routes(provider, ends, load_weight_lb)
    except NoRouteError as exc:
        names = [p.get("display_name") for p in (origin, destination)]
        if all(names):
            raise NoRouteError(f"{exc} Check the places: {names[0]} -> {names[1]}.") from exc
        raise
    if not raw:
        raise ProviderError("Routing service did not return a route.")
    routes = []
    for candidate in raw:
        if not routes or _is_distinct(candidate, routes, 0.5):
            routes.append(candidate)

    base = routes[0]
    max_miles = base["distance_miles"] * MAX_DETOUR_FACTOR + 10
    for round_specs in VIA_ROUNDS:
        if len(routes) >= wanted:
            break
        vias = [_via_point(base, f, share, side) for f, share in round_specs for side in (1, -1)]
        with ThreadPoolExecutor(max_workers=len(vias)) as pool:
            candidates = [c for c in pool.map(lambda v: _route_via(provider, ends, v, load_weight_lb), vias) if c]
        for candidate in sorted(candidates, key=lambda c: c["distance_miles"]):
            if len(routes) >= wanted:
                break
            if candidate["distance_miles"] <= max_miles and _is_distinct(candidate, routes):
                routes.append(candidate)
    return [{**r, "provider": provider} for r in routes[:wanted]]


# --------------------------------------------------------------------------- weather
_weather_cache = {}
_weather_lock = threading.Lock()


def weather_key(lat, lon, precise=False):
    """
    The forecast location used for a point (and the cache key for it).

    precise=True  -> rounded to 0.01 deg (~1 km). Used for checkpoints, whose weather
                     drives the risk classification and ranking.
    precise=False -> snapped to a 0.1 deg grid (~7 x 7 mi), cell centre. Used for the
                     heatmap: Open-Meteo bills every location as one API call, and the
                     grid lets nearby/overlapping heatmap points share one forecast.
    """
    if precise:
        return (round(lat, 2), round(lon, 2))
    g = WEATHER_GRID_DEG
    return (round(round(lat / g) * g, 4), round(round(lon / g) * g, 4))


def _to_inches(values, unit):
    unit = (unit or "inch").lower()
    factor = 1 / 2.54 if unit.startswith("cm") else 1 / 25.4 if unit.startswith("mm") else 1.0
    return [float(v or 0) * factor for v in values]


def _parse_location(payload):
    hourly = payload.get("hourly") or {}
    units = payload.get("hourly_units") or {}
    times = hourly.get("time") or []
    if not times:
        raise ProviderError("Weather provider returned no hourly forecast data.")
    rain = _to_inches(hourly.get("rain", []), units.get("rain"))
    showers = _to_inches(hourly.get("showers", []), units.get("showers"))
    n = len(times)
    rain = (rain + [0.0] * n)[:n]
    showers = (showers + [0.0] * n)[:n]
    return {
        "start": datetime.fromisoformat(times[0]).replace(tzinfo=timezone.utc),
        "wind": ([float(v or 0) for v in hourly.get("wind_speed_10m", [])] + [0.0] * n)[:n],
        # Rain excludes snow water (unlike total `precipitation`), so snow isn't double counted.
        "rain": [a + b for a, b in zip(rain, showers)],
        "snow": (_to_inches(hourly.get("snowfall", []), units.get("snowfall")) + [0.0] * n)[:n],
    }


def _fetch_chunk(keys):
    params = {
        "latitude": ",".join(str(k[0]) for k in keys),
        "longitude": ",".join(str(k[1]) for k in keys),
        "hourly": "wind_speed_10m,rain,showers,snowfall",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "UTC",
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
    }
    if OPEN_METEO_API_KEY:
        params["apikey"] = OPEN_METEO_API_KEY
    last_error, rate_limited = None, False
    for attempt in range(3):
        try:
            response = requests.get(OPEN_METEO_URL, params=params, timeout=30)
        except requests.RequestException as exc:
            last_error, rate_limited = exc, False
            time.sleep(1.2 * (attempt + 1))
            continue
        if response.status_code == 429:
            # Free-tier limits are per minute/hour/day; a 1-2 s retry never helps.
            last_error, rate_limited = "HTTP 429", True
            if attempt < 2:
                time.sleep(_retry_after_seconds(response, default=4 * (attempt + 1)))
            continue
        if response.status_code in (500, 502, 503, 504):
            last_error, rate_limited = f"HTTP {response.status_code}", False
            time.sleep(1.2 * (attempt + 1))
            continue
        try:
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"Weather service error: {exc}") from exc
        break
    else:
        if rate_limited:
            raise RateLimitedError(
                "The weather service (Open-Meteo free tier) is rate limiting this server. "
                "Wait a minute and try again, or choose a larger checkpoint interval."
            )
        raise ProviderError(f"Weather service error: {last_error}")

    payloads = payload if isinstance(payload, list) else [payload]
    if len(payloads) != len(keys):
        raise ProviderError("Weather provider returned an unexpected number of locations.")
    return [_parse_location(p) for p in payloads]


def _retry_after_seconds(response, default):
    try:
        value = float(response.headers.get("Retry-After", default))
    except (TypeError, ValueError):
        value = default
    return max(1.0, min(value, RATE_LIMIT_MAX_WAIT))


def fetch_hourly_series(keys):
    """
    keys: iterable of forecast locations, already produced by `weather_key` (the caller
    chooses precise or grid keys). Returns {key: series}. Keys are de-duplicated,
    batched into multi-coordinate requests and cached for 15 minutes - so changing
    the interval or re-running a trip is cheap.

    If Open-Meteo rate-limits us, forecasts up to WEATHER_STALE_MAX old are used
    instead (marked `"stale": True`) rather than failing the whole analysis.
    """
    keys = list(dict.fromkeys(keys))
    now = time.time()
    with _weather_lock:
        for k in [k for k, (ts, _) in _weather_cache.items() if now - ts > WEATHER_STALE_MAX]:
            del _weather_cache[k]  # keep the cache bounded on a long-running server
        missing = [k for k in keys if k not in _weather_cache or now - _weather_cache[k][0] > WEATHER_CACHE_TTL]

    stale_keys = set()
    if missing:
        chunks = [missing[i:i + WEATHER_CHUNK] for i in range(0, len(missing), WEATHER_CHUNK)]
        with ThreadPoolExecutor(max_workers=min(WEATHER_WORKERS, len(chunks))) as pool:
            futures = [(chunk, pool.submit(_fetch_chunk, chunk)) for chunk in chunks]
            for chunk, future in futures:
                try:
                    series_list = future.result()
                except RateLimitedError:
                    with _weather_lock:
                        if not all(k in _weather_cache for k in chunk):
                            raise
                    stale_keys.update(chunk)
                    continue
                with _weather_lock:
                    for key, series in zip(chunk, series_list):
                        _weather_cache[key] = (time.time(), series)
    with _weather_lock:
        return {k: ({**_weather_cache[k][1], "stale": True} if k in stale_keys else _weather_cache[k][1])
                for k in keys}


def weather_at(series, when):
    """Nearest forecast hour to `when`. `out_of_range` is set if it had to be clamped."""
    when_utc = when.astimezone(timezone.utc)
    idx = round((when_utc - series["start"]).total_seconds() / 3600)
    last = len(series["wind"]) - 1
    out_of_range = idx < 0 or idx > last
    idx = max(0, min(idx, last))
    return {
        "forecast_time": (series["start"] + timedelta(hours=idx)).isoformat(),
        "wind_mph": series["wind"][idx],
        "rain_in_per_hour": series["rain"][idx],
        "snow_in_per_hour": series["snow"][idx],
        "out_of_range": out_of_range,
    }


def hours_available_from(series, start):
    """How many hourly values exist at or after `start`."""
    idx = round((start.astimezone(timezone.utc) - series["start"]).total_seconds() / 3600)
    return max(0, len(series["wind"]) - max(idx, 0)) if idx < len(series["wind"]) else 0
