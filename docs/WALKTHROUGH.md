# Loom walkthrough script (target 7–8 minutes)

**Before recording**
- Pick a trip with real weather today: check a weather map for wind or precipitation along a corridor, or ask for a quick forecast scan. A calm day makes every route "Low" and hides the logic.
- Open the hosted app and run the trip once (wakes the free backend, warms the cache).
- Have the repo open on `risk_calculator.py`, `services.py`, `HeatLayer.tsx`.

| Time | Show | Say (key points) |
|---|---|---|
| 0:00–0:30 | Hosted app, empty state | What it does: compares up to 3 truck routes by weather **at the time the truck gets there**, recommends the safest, heatmap 0–48 h. |
| 0:30–1:30 | Fill the form: autocomplete origin/destination, departure, load 45,000 lb, 25-mile checkpoints → Analyze | Places come from autocomplete so coordinates are exact; load matters because wind rules depend on it. |
| 1:30–2:30 | Recommendation card + route cards | Read the plain-English reason. Ranking = No Travel → Severe → High miles → avg risk → time; avg risk within 0.05 counts as a tie so time can decide (how it balances risk vs time). Point at the risk strip: *where* the risk is. |
| 2:30–3:45 | Map: route colours + legend, click a checkpoint, then a table row (map flies to it) | Each checkpoint: ETA, forecast hour nearest the ETA, wind/rain/snow and which factor drove the level. |
| 3:45–4:45 | Heatmap: drag slider, press Play, zoom while playing | Purely client-side: no network calls, colours blend between hours, canvas follows zoom; route layers are memoised so only the canvas repaints. |
| 4:45–5:15 | Change load to 25,000 lb, re-run | Same weather, different risk: load rules (> 30,000 lb at 45–54 mph = No Travel; > 40,000 lb at 35–44 mph = Severe). |
| 5:15–6:45 | Code: `risk_calculator.py`, `services.py`, `providers.py` | Pure risk rules + 42 tests at every boundary; distance-weighted summaries; truck routing via OpenRouteService HGV (weight limits) with OSRM fallback; batched/cached weather, rate-limit handling. |
| 6:45–7:30 | README "Assumptions" + "Limitations", CI badge | Boundary interpretation, "Severe miles" includes No Travel, what is not checked (height/hazmat), free-tier limits. |
