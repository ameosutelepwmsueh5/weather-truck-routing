from django.urls import path
from routing.views import analyze_trip, health, places

urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/analyze/", analyze_trip, name="analyze-trip"),
    path("api/places/", places, name="places"),
]
