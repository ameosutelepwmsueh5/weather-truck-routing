import logging

from django.http import JsonResponse
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import exception_handler

from . import providers, services
from .providers import NoRouteError, ProviderError, RateLimitedError, search_places
from .serializers import AnalyzeRequestSerializer

logger = logging.getLogger(__name__)


class AnalyzeThrottle(AnonRateThrottle):
    scope = "analyze"


class PlacesThrottle(AnonRateThrottle):
    scope = "places"


def api_exception_handler(exc, context):
    """DRF errors (e.g. 429 throttling) use the same {"error": "..."} shape as our own."""
    response = exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict) and "detail" in response.data:
        response.data = {"error": str(response.data["detail"])}
    return response


@require_GET
def health(request):
    """Liveness + which upstream services this deployment is configured to use."""
    return JsonResponse({
        "status": "ok",
        "service": "weather-truck-routing-api",
        "routing": "OpenRouteService HGV" if providers.ORS_API_KEY else "OSRM (car)",
        "weather": "Open-Meteo" + (" (API key)" if providers.OPEN_METEO_API_KEY else ""),
    })


@api_view(["POST"])
@throttle_classes([AnalyzeThrottle])
def analyze_trip(request):
    serializer = AnalyzeRequestSerializer(data=request.data)
    if not serializer.is_valid():
        first = next(iter(serializer.errors.items()))
        message = f"{first[0]}: {first[1][0]}"
        return Response({"error": message, "fields": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    d = serializer.validated_data
    try:
        result = services.analyze(
            d["origin"], d["destination"], d["departure_time"],
            d["load_weight_lb"], d["checkpoint_interval_miles"],
        )
    except NoRouteError as exc:  # the trip is impossible as entered - the user must change it
        return Response({"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except RateLimitedError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE,
                        headers={"Retry-After": "60"})
    except ProviderError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    except Exception:  # noqa: BLE001 - never leak internals to the client
        logger.exception("Unhandled error while analysing trip")
        return Response({"error": "Unexpected server error while analysing the trip."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return Response(result)


@api_view(["GET"])
@throttle_classes([PlacesThrottle])
def places(request):
    """Autocomplete suggestions: GET /api/places/?q=<at least 3 characters>."""
    query = request.query_params.get("q", "").strip()
    if len(query) < 3:
        return Response({"results": []})
    try:
        return Response({"results": search_places(query)})
    except ProviderError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
