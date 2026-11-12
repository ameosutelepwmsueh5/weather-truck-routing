"""Run with:  python manage.py test   (or: python -m unittest routing.tests)"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from . import providers, services
from .geometry import cumulative_miles, mean_separation_miles, sample_route, simplify
from .risk_calculator import (
    classify_checkpoint, classify_rain, classify_snow, classify_wind,
    rank_routes, summarize_route,
)


_isolation = []


def setUpModule():
    """Tests never use real API keys from the developer's .env: default to the keyless providers."""
    for name in ("ORS_API_KEY", "OPEN_METEO_API_KEY"):
        patcher = mock.patch.object(providers, name, "")
        patcher.start()
        _isolation.append(patcher)


def tearDownModule():
    while _isolation:
        _isolation.pop().stop()


class WindAndLoadRules(unittest.TestCase):
    def test_thresholds_light_load(self):
        for mph, expected in [(24.9, "LOW"), (25, "MODERATE"), (34.9, "MODERATE"), (35, "HIGH"),
                              (44.9, "HIGH"), (45, "SEVERE"), (54.9, "SEVERE"), (55, "NO_TRAVEL")]:
            self.assertEqual(classify_wind(mph, 10000), expected, mph)

    def test_55_mph_is_no_travel_for_any_load(self):
        self.assertEqual(classify_wind(55, 0), "NO_TRAVEL")
        self.assertEqual(classify_wind(80, 1), "NO_TRAVEL")

    def test_45_to_54_heavy_load_is_no_travel(self):
        self.assertEqual(classify_wind(45, 30000), "SEVERE")      # exactly 30,000 is not > 30,000
        self.assertEqual(classify_wind(45, 30001), "NO_TRAVEL")
        self.assertEqual(classify_wind(54, 60000), "NO_TRAVEL")

    def test_35_to_44_very_heavy_load_is_severe(self):
        self.assertEqual(classify_wind(35, 40000), "HIGH")        # exactly 40,000 is not > 40,000
        self.assertEqual(classify_wind(35, 40001), "SEVERE")
        self.assertEqual(classify_wind(44, 90000), "SEVERE")

    def test_load_does_not_affect_low_or_moderate_wind(self):
        self.assertEqual(classify_wind(30, 100000), "MODERATE")
        self.assertEqual(classify_wind(10, 100000), "LOW")


class RainAndSnow(unittest.TestCase):
    def test_rain(self):
        for v, e in [(0.09, "LOW"), (0.10, "MODERATE"), (0.25, "HIGH"), (0.50, "SEVERE"),
                     (1.00, "SEVERE"), (1.01, "NO_TRAVEL")]:
            self.assertEqual(classify_rain(v), e, v)

    def test_snow(self):
        for v, e in [(0.49, "LOW"), (0.5, "MODERATE"), (1.0, "HIGH"), (2.0, "SEVERE"),
                     (3.0, "SEVERE"), (3.01, "NO_TRAVEL")]:
            self.assertEqual(classify_snow(v), e, v)

    def test_checkpoint_takes_worst_factor(self):
        r = classify_checkpoint(wind_mph=10, rain_in_per_hour=0.3, snow_in_per_hour=0.6, load_weight_lb=1000)
        self.assertEqual((r["wind_risk"], r["rain_risk"], r["snow_risk"]), ("LOW", "HIGH", "MODERATE"))
        self.assertEqual(r["risk_level"], "HIGH")
        self.assertEqual(r["risk_score"], 2)


def cp(level, miles):
    score = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "SEVERE": 3, "NO_TRAVEL": 4}[level]
    return {"risk_level": level, "risk_score": score, "segment_miles": miles}


def route(name, levels_miles, duration_min):
    cps = [cp(l, m) for l, m in levels_miles]
    return {"id": name, "name": name, "summary": summarize_route(cps, sum(m for _, m in levels_miles), duration_min)}


class SummaryAndRanking(unittest.TestCase):
    def test_summary_is_distance_weighted(self):
        s = summarize_route([cp("LOW", 10), cp("HIGH", 30), cp("SEVERE", 10), cp("NO_TRAVEL", 5)], 55, 90)
        self.assertEqual(s["high_miles"], 30)
        self.assertEqual(s["severe_miles"], 15)       # severe + no travel
        self.assertEqual(s["no_travel_miles"], 5)
        self.assertTrue(s["has_no_travel"])
        self.assertEqual(s["average_risk_score"], round((0 + 60 + 30 + 20) / 55, 2))

    def test_fewest_severe_miles_wins_even_if_slower(self):
        a = route("A", [("SEVERE", 20), ("LOW", 80)], 100)
        b = route("B", [("SEVERE", 10), ("LOW", 90)], 300)
        ranked, _ = rank_routes([a, b])
        self.assertEqual(ranked[0]["id"], "B")

    def test_high_miles_break_severe_ties(self):
        a = route("A", [("HIGH", 30), ("LOW", 70)], 100)
        b = route("B", [("HIGH", 10), ("LOW", 90)], 200)
        self.assertEqual(rank_routes([a, b])[0][0]["id"], "B")

    def test_average_risk_then_duration_break_ties(self):
        a = route("A", [("MODERATE", 50), ("LOW", 50)], 100)
        b = route("B", [("MODERATE", 20), ("LOW", 80)], 200)
        self.assertEqual(rank_routes([a, b])[0][0]["id"], "B")
        c = route("C", [("LOW", 100)], 120)
        d = route("D", [("LOW", 100)], 90)
        ranked, reason = rank_routes([c, d])
        self.assertEqual(ranked[0]["id"], "D")
        self.assertIn("shorter travel time", reason)

    def test_no_travel_route_never_beats_a_drivable_route(self):
        blocked = route("blocked", [("NO_TRAVEL", 2), ("LOW", 98)], 100)   # only 2 severe-or-worse miles
        severe = route("severe", [("SEVERE", 40), ("LOW", 60)], 100)
        ranked, _ = rank_routes([blocked, severe])
        self.assertEqual(ranked[0]["id"], "severe")
        self.assertTrue(ranked[1]["blocked"])

    def test_near_equal_average_risk_lets_travel_time_decide(self):
        # 0.42 vs 0.40 average risk is within tolerance, so the 2h-faster route wins.
        slow = route("slow", [("MODERATE", 40), ("LOW", 60)], 400)    # avg 0.40
        fast = route("fast", [("MODERATE", 42), ("LOW", 58)], 280)    # avg 0.42
        ranked, reason = rank_routes([slow, fast])
        self.assertEqual(ranked[0]["id"], "fast")
        self.assertIn("shorter travel time", reason)
        self.assertIn("time decides", reason)

    def test_clearly_lower_average_risk_still_beats_time(self):
        risky = route("risky", [("MODERATE", 60), ("LOW", 40)], 100)  # avg 0.60
        calm = route("calm", [("MODERATE", 20), ("LOW", 80)], 300)    # avg 0.20
        ranked, reason = rank_routes([risky, calm])
        self.assertEqual(ranked[0]["id"], "calm")
        self.assertIn("lower average risk", reason)

    def test_ranking_is_independent_of_input_order(self):
        rs = [route("a", [("MODERATE", 0), ("LOW", 100)], 300),     # avg 0.00
              route("b", [("MODERATE", 4), ("LOW", 96)], 200),      # avg 0.04
              route("c", [("MODERATE", 8), ("LOW", 92)], 100)]      # avg 0.08
        first = [r["id"] for r in rank_routes(list(rs))[0]]
        second = [r["id"] for r in rank_routes(list(reversed(rs)))[0]]
        self.assertEqual(first, second)
        self.assertEqual(first, ["b", "a", "c"])  # c is outside 0.05 of the best; b is faster than a

    def test_all_blocked_message(self):
        ranked, reason = rank_routes([route("A", [("NO_TRAVEL", 5)], 60), route("B", [("NO_TRAVEL", 9)], 50)])
        self.assertEqual(ranked[0]["id"], "A")
        self.assertIn("delaying departure", reason)


class Geometry(unittest.TestCase):
    LINE = [[-90.0, 40.0], [-89.0, 40.0], [-88.0, 40.0]]  # ~ 106 miles at 40N

    def test_samples_include_origin_and_destination_and_cover_full_length(self):
        total = cumulative_miles(self.LINE)[-1]
        samples = sample_route(self.LINE, 25)
        self.assertEqual(samples[0]["distance_miles"], 0)
        self.assertAlmostEqual(samples[-1]["distance_miles"], total, delta=0.01)
        self.assertAlmostEqual(sum(s["segment_miles"] for s in samples), total, delta=0.1)
        gaps = [b["distance_miles"] - a["distance_miles"] for a, b in zip(samples, samples[1:])]
        self.assertTrue(all(g <= 25.01 for g in gaps))

    def test_short_route_still_has_two_samples(self):
        self.assertEqual(len(sample_route([[-90, 40], [-89.9, 40]], 50)), 2)

    def test_separation_uses_line_not_just_vertices(self):
        dense = [[-90.0 + i * 0.1, 40.0] for i in range(21)]
        self.assertLess(mean_separation_miles(dense, self.LINE), 0.01)   # same road, sparse vertices
        shifted = [[x, y + 0.1] for x, y in self.LINE]                    # ~6.9 mi north
        self.assertAlmostEqual(mean_separation_miles(self.LINE, shifted), 6.9, delta=0.1)

    def test_simplify_keeps_corners_and_drops_collinear_points(self):
        pts = [[0, 0], [1, 0], [2, 0], [3, 0], [3, 3]]
        self.assertEqual(simplify(pts, 0.01), [[0, 0], [3, 0], [3, 3]])


def fake_series(start, wind=10.0, hours=192):
    return {"start": start, "wind": [wind] * hours, "rain": [0.0] * hours, "snow": [0.0] * hours}


class WeatherLookup(unittest.TestCase):
    def test_nearest_hour_and_clamping(self):
        start = datetime(2026, 11, 12, 0, tzinfo=timezone.utc)
        s = fake_series(start)
        s["wind"][5] = 40.0
        w = providers.weather_at(s, start + timedelta(hours=4, minutes=40))
        self.assertEqual(w["wind_mph"], 40.0)
        self.assertFalse(w["out_of_range"])
        self.assertTrue(providers.weather_at(s, start + timedelta(days=30))["out_of_range"])

    def test_unit_conversion(self):
        self.assertAlmostEqual(providers._to_inches([2.54], "cm")[0], 1.0)
        self.assertAlmostEqual(providers._to_inches([25.4], "mm")[0], 1.0)
        self.assertEqual(providers._to_inches([1.5, None], "inch"), [1.5, 0.0])

    def test_parse_location_uses_rain_not_total_precipitation(self):
        p = {"hourly_units": {"rain": "inch", "showers": "inch", "snowfall": "inch"},
             "hourly": {"time": ["2026-11-12T00:00", "2026-11-12T01:00"], "wind_speed_10m": [5, 6],
                        "rain": [0.1, 0.0], "showers": [0.05, None], "snowfall": [0.0, 1.2]}}
        out = providers._parse_location(p)
        self.assertAlmostEqual(out["rain"][0], 0.15)
        self.assertEqual(out["snow"], [0.0, 1.2])


def fake_osrm_route(coords):
    miles = cumulative_miles(coords)[-1]
    return {"geometry": {"coordinates": coords}, "distance": miles * providers.METERS_PER_MILE,
            "duration": miles / 60 * 3600}


class RouteGeneration(unittest.TestCase):
    ORIGIN = {"lat": 40.0, "lon": -90.0}
    DEST = {"lat": 40.0, "lon": -88.0}
    BASE = [[-90.0, 40.0], [-89.0, 40.0], [-88.0, 40.0]]

    def _fake_osrm(self, detour=True):
        calls = []

        def fake(coords_param, **_):
            calls.append(coords_param)
            pts = [[float(x) for x in p.split(",")] for p in coords_param.split(";")]
            if len(pts) == 2 or not detour:
                return [fake_osrm_route(self.BASE)]
            return [fake_osrm_route([pts[0], pts[1], pts[2]])]   # route bends through the via point
        return fake, calls

    def test_via_points_fill_up_to_three_distinct_routes(self):
        fake, calls = self._fake_osrm()
        with mock.patch.object(providers, "_osrm", side_effect=fake):
            routes = providers.get_routes(self.ORIGIN, self.DEST)
        self.assertEqual(len(routes), 3)
        self.assertEqual(len(calls), 3)          # base + one round of two via-points
        lats = sorted(r["coordinates"][1][1] for r in routes[1:])
        self.assertLess(lats[0], 40.0)           # one detour on each side
        self.assertGreater(lats[1], 40.0)

    def test_duplicate_detours_are_rejected_after_trying_every_round(self):
        fake, calls = self._fake_osrm(detour=False)
        with mock.patch.object(providers, "_osrm", side_effect=fake):
            routes = providers.get_routes(self.ORIGIN, self.DEST)
        self.assertEqual(len(routes), 1)
        self.assertEqual(len(calls), 1 + sum(2 * len(r) for r in providers.VIA_ROUNDS))

    def test_failed_detour_request_does_not_fail_analysis(self):
        def fake(coords_param, **_):
            if coords_param.count(";") == 1:
                return [fake_osrm_route(self.BASE)]
            raise providers.ProviderError("boom")
        with mock.patch.object(providers, "_osrm", side_effect=fake):
            self.assertEqual(len(providers.get_routes(self.ORIGIN, self.DEST)), 1)


class RoutingErrors(unittest.TestCase):
    def test_osrm_no_route_becomes_clear_no_route_error(self):
        resp = mock.Mock(ok=False, status_code=400)
        resp.json.return_value = {"code": "NoRoute", "message": "Impossible route between points"}
        chicago = {"lat": 41.88, "lon": -87.62, "display_name": "Chicago"}
        borneo = {"lat": -2.48, "lon": 117.89, "display_name": "Borneo"}
        with mock.patch.object(providers.requests, "get", return_value=resp):
            with self.assertRaises(providers.NoRouteError) as ctx:
                providers.get_routes(chicago, borneo)
        self.assertIn("No drivable road", str(ctx.exception))
        self.assertIn("Chicago -> Borneo", str(ctx.exception))

    def test_unreachable_via_point_is_skipped_not_fatal(self):
        base = [[-90.0, 40.0], [-89.0, 40.0], [-88.0, 40.0]]

        def fake(coords_param, **_):
            if coords_param.count(";") == 1:
                return [fake_osrm_route(base)]
            raise providers.NoRouteError("via point in a lake")
        with mock.patch.object(providers, "_osrm", side_effect=fake):
            self.assertEqual(len(providers.get_routes({"lat": 40, "lon": -90}, {"lat": 40, "lon": -88})), 1)

    def test_geocoding_is_limited_to_configured_countries(self):
        self.assertEqual(providers._nominatim_params("Paris", 1)["countrycodes"], providers.GEOCODE_COUNTRIES)

    def test_place_search_uses_photon_and_filters_countries(self):
        def feature(name, cc, lon, lat, **props):
            return {"geometry": {"coordinates": [lon, lat]},
                    "properties": {"name": name, "countrycode": cc, "state": props.get("state"), "country": props.get("country")}}
        payload = {"features": [
            feature("Paris", "US", -95.55, 33.66, state="Texas", country="United States"),
            feature("Paris", "FR", 2.35, 48.85, country="France"),
            feature("Paris", "US", -95.55, 33.66, state="Texas", country="United States"),   # duplicate label
        ]}
        resp = mock.Mock(status_code=200)
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        providers._search_places_cached.cache_clear()
        self.addCleanup(providers._search_places_cached.cache_clear)
        with mock.patch.object(providers.requests, "get", return_value=resp) as get:
            out = providers.search_places("  Paris ")
        self.assertEqual(get.call_args.args[0], providers.PHOTON_URL)
        self.assertEqual(out, [{"display_name": "Paris, Texas, United States", "lat": 33.66, "lon": -95.55}])
        self.assertEqual(providers.search_places("Pa"), [])   # too short: no request


def ors_response(status, payload):
    r = mock.Mock(status_code=status, ok=status < 400)
    r.json.return_value = payload
    return r


def ors_feature(coords, miles, minutes):
    return {"geometry": {"coordinates": coords},
            "properties": {"summary": {"distance": miles * providers.METERS_PER_MILE, "duration": minutes * 60}}}


class TruckRouting(unittest.TestCase):
    """Optional OpenRouteService HGV routing (ORS_API_KEY set)."""
    ORIGIN = {"lat": 40.0, "lon": -90.0, "display_name": "A"}
    DEST = {"lat": 40.0, "lon": -89.7, "display_name": "B"}   # ~16 mi: short enough for ORS alternatives

    def setUp(self):
        key = mock.patch.object(providers, "ORS_API_KEY", "test-key")
        key.start()
        self.addCleanup(key.stop)

    def test_uses_hgv_profile_with_gross_weight_and_tags_provider(self):
        line = [[-90.0, 40.0], [-89.7, 40.0]]
        with mock.patch.object(providers.requests, "post",
                               return_value=ors_response(200, {"features": [ors_feature(line, 16, 20)]})) as post, \
             mock.patch.object(providers, "_osrm", side_effect=AssertionError("OSRM must not be used")), \
             mock.patch.object(providers, "VIA_ROUNDS", []):
            routes = providers.get_routes(self.ORIGIN, self.DEST, load_weight_lb=45000)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["options"]["vehicle_type"], "hgv")
        self.assertAlmostEqual(body["options"]["profile_params"]["restrictions"]["weight"],
                               round((45000 + providers.TRUCK_EMPTY_WEIGHT_LB) / providers.LB_PER_TONNE, 1))
        self.assertIn("alternative_routes", body)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "test-key")
        self.assertEqual(routes[0]["provider"], "ors-hgv")
        self.assertAlmostEqual(routes[0]["distance_miles"], 16)

    def test_long_trips_do_not_request_ors_alternatives(self):
        far = {"lat": 40.0, "lon": -80.0, "display_name": "C"}
        with mock.patch.object(providers.requests, "post",
                               return_value=ors_response(200, {"features": [ors_feature([[-90, 40], [-80, 40]], 530, 500)]})) as post, \
             mock.patch.object(providers, "VIA_ROUNDS", []):
            providers.get_routes(self.ORIGIN, far, load_weight_lb=1000)
        self.assertNotIn("alternative_routes", post.call_args.kwargs["json"])

    def test_falls_back_to_osrm_when_truck_router_fails(self):
        line = [[-90.0, 40.0], [-89.7, 40.0]]
        with mock.patch.object(providers.requests, "post",
                               return_value=ors_response(403, {"error": {"code": 0, "message": "bad key"}})), \
             mock.patch.object(providers, "_osrm", return_value=[fake_osrm_route(line)]), \
             mock.patch.object(providers, "VIA_ROUNDS", []):
            routes = providers.get_routes(self.ORIGIN, self.DEST)
        self.assertEqual(routes[0]["provider"], "osrm-car")

    def test_ors_no_route_is_reported_not_retried(self):
        with mock.patch.object(providers.requests, "post",
                               return_value=ors_response(404, {"error": {"code": 2009, "message": "no route"}})), \
             mock.patch.object(providers, "_osrm", side_effect=AssertionError("must not fall back")):
            with self.assertRaises(providers.NoRouteError):
                providers.get_routes(self.ORIGIN, self.DEST)


def _django_configured():
    try:
        from django.conf import settings
        return settings.configured
    except ImportError:
        return False


@unittest.skipUnless(_django_configured(), "needs Django settings: run `python manage.py test`")
class HealthEndpoint(unittest.TestCase):
    def test_reports_configured_providers(self):
        from django.test import RequestFactory
        from . import views

        request = RequestFactory().get("/api/health/")
        body = json.loads(views.health(request).content)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["routing"], "OSRM (car)")          # tests run keyless (see setUpModule)
        with mock.patch.object(providers, "ORS_API_KEY", "k"):
            self.assertEqual(json.loads(views.health(request).content)["routing"], "OpenRouteService HGV")


class HeatSpacing(unittest.TestCase):
    def test_checkpoints_double_as_heat_points_when_dense_enough(self):
        self.assertEqual(services.heat_spacing_miles(10, 200), 10)
        self.assertEqual(services.heat_spacing_miles(25, 200), 25)

    def test_sparse_checkpoints_get_extra_points_widened_on_long_trips(self):
        self.assertEqual(services.heat_spacing_miles(50, 200), 25)
        self.assertEqual(services.heat_spacing_miles(50, 3300), 41.25)   # <= 80 extra points per route
        self.assertEqual(services.heat_spacing_miles(25, 3300), 25)      # 25-mi checkpoints are reused as-is


class WeatherRateLimiting(unittest.TestCase):
    def setUp(self):
        providers._weather_cache.clear()
        self.addCleanup(providers._weather_cache.clear)
        sleep = mock.patch.object(providers.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    @staticmethod
    def _response(status, payload=None):
        r = mock.Mock(status_code=status, headers={})
        r.json.return_value = payload
        r.raise_for_status.return_value = None
        return r

    def test_nearby_points_share_one_forecast_location(self):
        self.assertEqual(providers.weather_key(40.01, -89.99), providers.weather_key(40.04, -90.03))
        self.assertNotEqual(providers.weather_key(40.0, -90.0), providers.weather_key(40.2, -90.0))

    def test_429_raises_rate_limited_error_without_cache(self):
        with mock.patch.object(providers.requests, "get", return_value=self._response(429)) as get:
            with self.assertRaises(providers.RateLimitedError):
                providers.fetch_hourly_series([(40.0, -90.0)])
        self.assertEqual(get.call_count, 3)

    def test_429_falls_back_to_stale_cache(self):
        key = providers.weather_key(40.0, -90.0)
        old = fake_series(datetime(2026, 11, 12, tzinfo=timezone.utc))
        providers._weather_cache[key] = (providers.time.time() - providers.WEATHER_CACHE_TTL - 60, old)
        with mock.patch.object(providers.requests, "get", return_value=self._response(429)):
            out = providers.fetch_hourly_series([(40.0, -90.0)])
        self.assertTrue(out[key]["stale"])
        self.assertEqual(out[key]["wind"], old["wind"])


class ServiceIntegration(unittest.TestCase):
    """Full pipeline with providers mocked (no network)."""

    def test_end_to_end_with_mocked_providers(self):
        line_a = [[-90.0, 40.0], [-89.0, 40.0], [-88.0, 40.0]]
        line_b = [[-90.0, 40.0], [-89.0, 40.6], [-88.0, 40.0]]
        routes = [
            {"coordinates": line_a, "distance_miles": 106.0, "duration_seconds": 6000},
            {"coordinates": line_b, "distance_miles": 130.0, "duration_seconds": 7600},
        ]
        departure = datetime(2026, 11, 12, 8, tzinfo=timezone.utc)

        def fake_fetch(keys):
            out = {}
            for k in keys:
                lat, lon = k
                s = fake_series(departure - timedelta(hours=8))
                if abs(lat - 40.0) < 0.05 and -89.8 < lon < -88.2:   # the direct route's middle is windy
                    s["wind"] = [41.0] * len(s["wind"])
                out[k] = s
            return out

        with mock.patch.object(services, "geocode_place", side_effect=lambda t: {"lat": 40, "lon": -90, "display_name": t}), \
             mock.patch.object(services, "get_routes", return_value=routes), \
             mock.patch.object(services, "fetch_hourly_series", side_effect=fake_fetch):
            heavy = services.analyze("A", "B", departure, 45000, 25)
            light = services.analyze("A", "B", departure, 20000, 25)

        # 41 mph + 45,000 lb -> SEVERE on direct route, so the detour wins despite being slower.
        self.assertEqual(heavy["routes"][0]["geometry"][1][1] > 40.2, True)
        self.assertEqual(heavy["routes"][0]["summary"]["severe_miles"], 0)
        self.assertGreater(heavy["routes"][1]["summary"]["severe_miles"], 0)
        # 41 mph + 20,000 lb -> HIGH only; the direct route is faster, but high miles still decide first.
        self.assertEqual(light["routes"][0]["id"], heavy["routes"][0]["id"])
        self.assertTrue(light["recommendation_reason"])
        # Heatmap has 49 hourly scores per point and ETAs are monotonic.
        self.assertEqual(len(heavy["heatmap"]["points"][0]["scores"]), 49)
        etas = [c["eta"] for c in heavy["routes"][1]["checkpoints"]]
        self.assertEqual(etas, sorted(etas))

    def test_checkpoints_use_exact_location_and_heatmap_uses_grid(self):
        line = [[-90.0, 40.0], [-88.0, 40.0]]
        requested = []

        def fake_fetch(keys):
            requested.extend(keys)
            return {k: fake_series(datetime(2026, 11, 12, tzinfo=timezone.utc)) for k in keys}

        with mock.patch.object(services, "get_routes",
                               return_value=[{"coordinates": line, "distance_miles": 106, "duration_seconds": 6000}]), \
             mock.patch.object(services, "fetch_hourly_series", side_effect=fake_fetch):
            res = services.analyze({"lat": 40, "lon": -90, "display_name": "A"}, {"lat": 40, "lon": -88, "display_name": "B"},
                                   datetime(2026, 11, 12, 8, tzinfo=timezone.utc), 20000, 50)
        cp_keys = {providers.weather_key(c["coordinates"][1], c["coordinates"][0], precise=True)
                   for c in res["routes"][0]["checkpoints"]}
        self.assertTrue(cp_keys <= set(requested))                       # exact (~1 km) checkpoint locations
        grid_keys = set(requested) - cp_keys
        self.assertTrue(grid_keys)                                       # 25-mi heatmap points on the 0.1 deg grid
        self.assertTrue(all(abs(k[1] * 10 - round(k[1] * 10)) < 1e-9 for k in grid_keys))


if __name__ == "__main__":
    unittest.main()
