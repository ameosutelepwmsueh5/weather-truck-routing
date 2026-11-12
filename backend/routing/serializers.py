from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

MAX_DAYS_AHEAD = 4  # forecast window fetched is ~7 days; leave room for 48h heatmap + trip time


class PlaceField(serializers.Field):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError(
                "Please select a location from the search results."
            )

        try:
            lat = float(data["lat"])
            lon = float(data["lon"])
            display_name = str(data["display_name"]).strip()

            if not (-90 <= lat <= 90):
                raise ValueError()

            if not (-180 <= lon <= 180):
                raise ValueError()

            if not display_name:
                raise ValueError()

        except (KeyError, TypeError, ValueError):
            raise serializers.ValidationError(
                "Invalid selected location."
            )

        return {
            "lat": lat,
            "lon": lon,
            "display_name": display_name,
        }

    def to_representation(self, value):
        return value

class AnalyzeRequestSerializer(serializers.Serializer):
    origin = PlaceField()
    destination = PlaceField()
    departure_time = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0, max_value=200000)
    checkpoint_interval_miles = serializers.ChoiceField(choices=[10, 25, 50], default=25)

    def validate_departure_time(self, value):
        now = timezone.now()
        if value < now - timedelta(hours=24):
            raise serializers.ValidationError("Departure cannot be more than 24 hours in the past.")
        if value > now + timedelta(days=MAX_DAYS_AHEAD):
            raise serializers.ValidationError(f"Departure must be within {MAX_DAYS_AHEAD} days (forecast range).")
        return value
