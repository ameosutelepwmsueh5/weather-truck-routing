"""Risk classification, route summaries and ranking. Pure Python (no Django)."""

RISK_SCORE = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "SEVERE": 3, "NO_TRAVEL": 4}
RISK_LABEL = {"LOW": "Low", "MODERATE": "Moderate", "HIGH": "High", "SEVERE": "Severe", "NO_TRAVEL": "No Travel"}

# Boundary rule: a value exactly on a threshold falls in the HIGHER category
# (e.g. wind 25 mph = Moderate, 35 mph = High, 45 mph = Severe, 55 mph = No Travel).
# Rain/snow "No Travel" is strictly above the top of the Severe band (> 1.00 / > 3.0).


def classify_wind(wind_mph: float, load_weight_lb: float) -> str:
    if wind_mph >= 55:
        return "NO_TRAVEL"
    if wind_mph >= 45:
        return "NO_TRAVEL" if load_weight_lb > 30000 else "SEVERE"
    if wind_mph >= 35:
        return "SEVERE" if load_weight_lb > 40000 else "HIGH"
    if wind_mph >= 25:
        return "MODERATE"
    return "LOW"


def classify_rain(rain_in_per_hour: float) -> str:
    if rain_in_per_hour > 1.00:
        return "NO_TRAVEL"
    if rain_in_per_hour >= 0.50:
        return "SEVERE"
    if rain_in_per_hour >= 0.25:
        return "HIGH"
    if rain_in_per_hour >= 0.10:
        return "MODERATE"
    return "LOW"


def classify_snow(snow_in_per_hour: float) -> str:
    if snow_in_per_hour > 3.00:
        return "NO_TRAVEL"
    if snow_in_per_hour >= 2.00:
        return "SEVERE"
    if snow_in_per_hour >= 1.00:
        return "HIGH"
    if snow_in_per_hour >= 0.50:
        return "MODERATE"
    return "LOW"


def classify_checkpoint(wind_mph, rain_in_per_hour, snow_in_per_hour, load_weight_lb):
    categories = [
        classify_wind(wind_mph, load_weight_lb),
        classify_rain(rain_in_per_hour),
        classify_snow(snow_in_per_hour),
    ]
    highest = max(categories, key=lambda item: RISK_SCORE[item])
    return {
        "risk_level": highest,
        "wind_risk": categories[0],
        "rain_risk": categories[1],
        "snow_risk": categories[2],
        "risk_score": RISK_SCORE[highest],
    }


def summarize_route(checkpoints, distance_miles, duration_minutes):
    """Distance-weighted route summary. Each checkpoint covers `segment_miles`."""
    severe_miles = no_travel_miles = high_miles = weighted = covered = 0.0
    for cp in checkpoints:
        segment = float(cp.get("segment_miles", 0))
        covered += segment
        weighted += cp["risk_score"] * segment
        if cp["risk_level"] == "NO_TRAVEL":
            no_travel_miles += segment
            severe_miles += segment  # "Severe miles" includes No Travel miles
        elif cp["risk_level"] == "SEVERE":
            severe_miles += segment
        elif cp["risk_level"] == "HIGH":
            high_miles += segment
    return {
        "severe_miles": round(severe_miles, 1),
        "no_travel_miles": round(no_travel_miles, 1),
        "high_miles": round(high_miles, 1),
        "average_risk_score": round(weighted / covered, 2) if covered else 0.0,
        "duration_minutes": round(duration_minutes),
        "distance_miles": round(distance_miles, 1),
        "has_no_travel": no_travel_miles > 0,
        "max_risk": max((cp["risk_level"] for cp in checkpoints), key=lambda r: RISK_SCORE[r], default="LOW"),
    }


# Average risk is a continuous number, so two routes almost never tie on it exactly and
# a strict comparison would let a 0.01 difference outweigh hours of extra driving.
# Routes whose average risk is within this margin of the best are treated as equally
# risky, and travel time decides between them ("balancing weather risk and travel time").
AVG_RISK_TOLERANCE = 0.05

# Exact-match criteria, compared in order (all "fewer is better"). Driving through a
# No Travel zone is worse than any amount of plain Severe, so it is compared first.
_MILE_CRITERIA = [
    ("no_travel_miles", "No Travel miles"),
    ("severe_miles", "Severe miles"),
    ("high_miles", "High-risk miles"),
]


def _pick_best(candidates):
    """
    The brief's preference order: fewest Severe miles, fewest High miles, lowest
    average risk (within AVG_RISK_TOLERANCE), shortest time. Filtering against the
    best value (rather than pairwise tolerance) keeps the result deterministic.
    """
    pool = list(candidates)
    for key, _label in _MILE_CRITERIA:
        lowest = min(r["summary"][key] for r in pool)
        pool = [r for r in pool if r["summary"][key] == lowest]
    lowest_avg = min(r["summary"]["average_risk_score"] for r in pool)
    pool = [r for r in pool if r["summary"]["average_risk_score"] <= lowest_avg + AVG_RISK_TOLERANCE + 1e-9]
    return min(pool, key=lambda r: (r["summary"]["duration_minutes"], r["summary"]["average_risk_score"]))


def _fmt(key, value):
    if key == "duration_minutes":
        h, m = divmod(int(round(value)), 60)
        return f"{h}h {m:02d}m" if h else f"{m}m"
    if key == "average_risk_score":
        return f"{value:.2f}"
    return f"{value:.1f} mi"


def rank_routes(routes):
    """Order routes best-first, set rank/recommended flags, and explain the pick."""
    remaining = list(routes)
    routes = []
    while remaining:
        best = _pick_best(remaining)
        routes.append(best)
        remaining.remove(best)
    for rank, route in enumerate(routes, start=1):
        route["rank"] = rank
        route["recommended"] = rank == 1
        route["blocked"] = route["summary"]["has_no_travel"]
    if routes:
        fastest = min(routes, key=lambda r: r["summary"]["duration_minutes"])
        for route in routes:
            route["fastest"] = route is fastest
    return routes, recommendation_reason(routes)


def recommendation_reason(ranked):
    if not ranked:
        return ""
    best = ranked[0]
    if all(r["blocked"] for r in ranked):
        return (
            "Every route crosses at least one No Travel checkpoint for this load and departure time. "
            f"{best['name']} has the least No Travel distance, but consider delaying departure or reducing the load."
        )
    if len(ranked) == 1:
        return f"Only one route was available, so {best['name']} is the only option to evaluate."

    runner_up = ranked[1]
    a, b = best["summary"], runner_up["summary"]
    head = f"{best['name']} is recommended: it has"
    tail = f"than {runner_up['name']}."
    for key, label in _MILE_CRITERIA:
        if a[key] != b[key]:
            return f"{head} {_fmt(key, b[key] - a[key])} fewer {label.lower()} {tail}"

    avg_a, avg_b = a["average_risk_score"], b["average_risk_score"]
    dur_a, dur_b = a["duration_minutes"], b["duration_minutes"]
    risk = f"({_fmt('average_risk_score', avg_a)} vs {_fmt('average_risk_score', avg_b)})"
    time = f"({_fmt('duration_minutes', dur_a)} vs {_fmt('duration_minutes', dur_b)})"
    if avg_b - avg_a > AVG_RISK_TOLERANCE + 1e-9:
        return f"{head} a lower average risk {risk} {tail}"
    if dur_a < dur_b:
        if avg_a != avg_b:
            return (f"{head} a shorter travel time {time} {tail} Their average risk is "
                    f"within {AVG_RISK_TOLERANCE} {risk}, so time decides.")
        return f"{head} a shorter travel time {time} {tail}"
    if avg_a < avg_b:
        return f"{head} a lower average risk {risk} {tail}"
    return f"{best['name']} is recommended; it ties with the other routes on every criterion."
