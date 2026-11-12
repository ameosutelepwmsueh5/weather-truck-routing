import { FormEvent, useState } from "react";
import { Truck, Clock3, Route } from "lucide-react";
import type { TripInput } from "../types";
import type { Place } from "../api";
import LocationAutocomplete from "./LocationAutocomplete";

interface Props {
  onSubmit: (values: TripInput) => void;
  loading: boolean;
}

function localDateTimeValue() {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setMinutes(0, 0, 0);
  const offset = d.getTimezoneOffset();

  return new Date(d.getTime() - offset * 60000).toISOString().slice(0, 16);
}

export default function TripForm({ onSubmit, loading }: Props) {
  const [origin, setOrigin] = useState<Place | null>(null);
  const [destination, setDestination] = useState<Place | null>(null);
  const [formError, setFormError] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");

    if (!origin || !destination) {
      setFormError("Please search and select both your origin and destination.");
      return;
    }

    if (origin.lat === destination.lat && origin.lon === destination.lon) {
      setFormError("Origin and destination cannot be the same location.");
      return;
    }

    const form = new FormData(event.currentTarget);

    const departureValue = String(form.get("departure_time") || "");

    onSubmit({
      origin,
      destination,
      departure_time: new Date(departureValue).toISOString(),
      load_weight_lb: Number(form.get("load_weight_lb")),
      checkpoint_interval_miles: Number(form.get("checkpoint_interval_miles")),
    });
  }

  return (
    <form onSubmit={handleSubmit} className="panel form-panel">
      <div className="section-heading">
        <div className="icon-tile">
          <Route size={19} />
        </div>

        <div>
          <h2>Plan your trip</h2>
          <p>Search and select your route locations</p>
        </div>
      </div>

      <LocationAutocomplete label="Origin" placeholder="Search starting location..." onSelect={setOrigin} />

      <LocationAutocomplete
        label="Destination"
        placeholder="Search destination..."
        onSelect={setDestination}
      />

      <label className="field-label">
        <Clock3 size={15} />
        Departure date & time
      </label>

      <input
        className="field"
        type="datetime-local"
        name="departure_time"
        required
        defaultValue={localDateTimeValue()}
      />

      <label className="field-label">
        <Truck size={15} />
        Load weight (lb)
      </label>

      <input
        className="field"
        type="number"
        name="load_weight_lb"
        min="0"
        max="200000"
        step="1"
        required
        defaultValue="25000"
      />

      <label className="field-label">Weather checkpoint interval</label>

      <select className="field" name="checkpoint_interval_miles" defaultValue="25">
        <option value="10">Every 10 miles</option>
        <option value="25">Every 25 miles</option>
        <option value="50">Every 50 miles</option>
      </select>

      {formError && <p className="location-error">{formError}</p>}

      <button className="primary-button" type="submit" disabled={loading}>
        {loading ? (
          <>
            <span className="spinner" />
            Analyzing routes...
          </>
        ) : (
          "Analyze safest routes"
        )}
      </button>

      <p className="form-footnote">
        Select a matching place from the search results before analyzing your trip.
      </p>
    </form>
  );
}
