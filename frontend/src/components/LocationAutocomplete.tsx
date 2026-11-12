import { KeyboardEvent, useEffect, useId, useState } from "react";
import { CheckCircle2, Loader2, MapPin, Search } from "lucide-react";
import { searchPlaces, type Place } from "../api";

interface Props {
  label: string;
  placeholder: string;
  onSelect: (place: Place | null) => void;
  initialValue?: string;
}

/**
 * Place search with a keyboard-accessible suggestion list (ARIA combobox):
 * Arrow keys move, Enter picks, Escape closes; clicking elsewhere closes it too.
 */
export default function LocationAutocomplete({ label, placeholder, onSelect, initialValue = "" }: Props) {
  const id = useId();
  const listId = `${id}-list`;
  const [query, setQuery] = useState(initialValue);
  const [results, setResults] = useState<Place[]>([]);
  const [selected, setSelected] = useState<Place | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    if (selected || query.trim().length < 3) {
      setResults([]);
      setLoading(false);
      setSearched(false);
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const places = await searchPlaces(query);
        if (!cancelled) {
          setResults(places);
          setActive(places.length ? 0 : -1);
          setSearched(true);
        }
      } catch {
        if (!cancelled) {
          setResults([]);
          setError("Unable to search places. Please try again.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 400);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, selected]);

  function handleChange(value: string) {
    setQuery(value);
    setSelected(null);
    setResults([]);
    setOpen(true);
    onSelect(null);
  }

  function handleSelect(place: Place) {
    setSelected(place);
    setQuery(place.display_name);
    setResults([]);
    setOpen(false);
    onSelect(place);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    const showing = open && results.length > 0;
    if (event.key === "ArrowDown" && results.length) {
      event.preventDefault();
      setOpen(true);
      setActive((i) => (i + 1) % results.length);
    } else if (event.key === "ArrowUp" && showing) {
      event.preventDefault();
      setActive((i) => (i <= 0 ? results.length - 1 : i - 1));
    } else if (event.key === "Enter" && showing && active >= 0) {
      event.preventDefault(); // pick the place instead of submitting the form
      handleSelect(results[active]);
    } else if (event.key === "Escape" && showing) {
      event.preventDefault();
      setOpen(false);
    }
  }

  const showList = open && results.length > 0;

  return (
    <div className="location-search">
      <label className="field-label" htmlFor={`${id}-input`}>
        <MapPin size={15} />
        {label}
      </label>

      <div className="location-input-wrap">
        <input
          id={`${id}-input`}
          className="field"
          type="text"
          value={query}
          placeholder={placeholder}
          autoComplete="off"
          required
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={showList && active >= 0 ? `${id}-opt-${active}` : undefined}
          onChange={(event) => handleChange(event.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
        />

        <span className={`location-search-icon ${selected ? "ok" : ""}`} aria-hidden>
          {loading ? (
            <Loader2 size={17} className="location-spinner" />
          ) : selected ? (
            <CheckCircle2 size={17} />
          ) : (
            <Search size={17} />
          )}
        </span>
      </div>

      {showList && (
        <ul className="location-results" id={listId} role="listbox" aria-label={`${label} suggestions`}>
          {results.map((place, index) => (
            <li
              key={`${place.lat}-${place.lon}-${index}`}
              id={`${id}-opt-${index}`}
              role="option"
              aria-selected={index === active}
              className={`location-result ${index === active ? "active" : ""}`}
              // mousedown (not click) so the pick lands before the input's blur closes the list
              onMouseDown={(event) => {
                event.preventDefault();
                handleSelect(place);
              }}
              onMouseEnter={() => setActive(index)}
            >
              <MapPin size={16} />
              <span>{place.display_name}</span>
            </li>
          ))}
        </ul>
      )}

      {searched && !loading && !selected && results.length === 0 && !error && (
        <p className="location-hint">No matching places found. Try a more specific search.</p>
      )}

      {error && <p className="location-error">{error}</p>}
    </div>
  );
}
