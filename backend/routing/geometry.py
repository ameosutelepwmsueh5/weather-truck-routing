"""Pure geometry helpers (no Django / network). Coordinates are [lon, lat]."""
import math
from bisect import bisect_left

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(a, b):
    lat1, lon1 = math.radians(a[1]), math.radians(a[0])
    lat2, lon2 = math.radians(b[1]), math.radians(b[0])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return EARTH_RADIUS_MILES * 2 * math.asin(math.sqrt(h))


def cumulative_miles(coordinates):
    cumulative = [0.0]
    for i in range(1, len(coordinates)):
        cumulative.append(cumulative[-1] + haversine_miles(coordinates[i - 1], coordinates[i]))
    return cumulative


def point_at_distance(coordinates, cumulative, target):
    """Linearly interpolate the [lon, lat] located `target` miles along the line."""
    if target <= 0:
        return list(coordinates[0])
    if target >= cumulative[-1]:
        return list(coordinates[-1])
    idx = bisect_left(cumulative, target)
    before, after = cumulative[idx - 1], cumulative[idx]
    fraction = 0 if after == before else (target - before) / (after - before)
    c1, c2 = coordinates[idx - 1], coordinates[idx]
    return [c1[0] + (c2[0] - c1[0]) * fraction, c1[1] + (c2[1] - c1[1]) * fraction]


def sample_route(coordinates, interval_miles):
    """
    Sample the route at mile 0, every `interval_miles`, and at the destination.

    Each sample gets `segment_miles`: the stretch of road it represents (half the
    distance to each neighbour). The segment miles add up to the full route length,
    so risk-miles are weighted fairly (the origin is sampled too).
    """
    if len(coordinates) < 2 or interval_miles <= 0:
        return []
    cumulative = cumulative_miles(coordinates)
    total = cumulative[-1]
    if total <= 0:
        return []

    distances = [0.0]
    step = interval_miles
    while step < total:
        distances.append(step)
        step += interval_miles
    if total - distances[-1] > 0.5:
        distances.append(total)
    else:
        distances[-1] = total

    samples = []
    for i, d in enumerate(distances):
        prev_d = distances[i - 1] if i > 0 else d
        next_d = distances[i + 1] if i < len(distances) - 1 else d
        coverage = ((d - prev_d) / 2) + ((next_d - d) / 2)
        samples.append({
            "distance_miles": round(d, 2),
            "segment_miles": round(coverage, 3),
            "coordinates": point_at_distance(coordinates, cumulative, d),
        })
    return samples


def simplify(coordinates, tolerance_deg=0.0008):
    """Iterative Ramer-Douglas-Peucker. ~0.0008 deg is roughly 90 m."""
    n = len(coordinates)
    if n <= 2:
        return [list(c) for c in coordinates]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        ax, ay = coordinates[start]
        bx, by = coordinates[end]
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        max_dist, max_idx = 0.0, None
        for i in range(start + 1, end):
            px, py = coordinates[i]
            if length_sq == 0:
                dist = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
                dist = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if dist > max_dist:
                max_dist, max_idx = dist, i
        if max_idx is not None and max_dist > tolerance_deg:
            keep[max_idx] = True
            stack.append((start, max_idx))
            stack.append((max_idx, end))
    return [list(coordinates[i]) for i in range(n) if keep[i]]


def _point_segment_miles(p, a, b):
    """Distance from p to segment a-b (local flat projection; fine at these scales)."""
    k = math.cos(math.radians(p[1]))
    ax, ay = (a[0] - p[0]) * k * 69.0, (a[1] - p[1]) * 69.0
    bx, by = (b[0] - p[0]) * k * 69.0, (b[1] - p[1]) * 69.0
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    t = 0.0 if length_sq == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length_sq))
    return math.hypot(ax + t * dx, ay + t * dy)


def mean_separation_miles(route_a, route_b, samples=24):
    """
    Average distance from points along route_a to the nearest point on route_b's
    line (not just its vertices - long straight highways can have vertices miles apart).
    """
    if len(route_a) < 2 or len(route_b) < 2:
        return 0.0
    cum_a = cumulative_miles(route_a)
    total = cum_a[-1]
    if total <= 0:
        return 0.0
    b_points = route_b if len(route_b) <= 400 else list(route_b[:: max(1, len(route_b) // 400)]) + [route_b[-1]]
    segments = list(zip(b_points, b_points[1:]))
    dists = []
    for k in range(samples):
        p = point_at_distance(route_a, cum_a, total * k / (samples - 1))
        dists.append(min(_point_segment_miles(p, a, b) for a, b in segments))
    return sum(dists) / len(dists)
