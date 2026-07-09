# Waffle House Route Explorer (Mapbox globe)

Interactive globe app that animates the TSP tours produced by the pipeline.

## Run

Serve the **repo root** over HTTP (the app reads `../output/routes/*.geojson`):

```bash
cd /Users/mattforrest/Documents/waffle-house
python3 -m http.server 8000
# then open:
open http://localhost:8000/app/
```

First load asks for a **Mapbox public token** (`pk.…`). It's stored in your
browser's localStorage — paste it once. (Or hard-code `HARDCODED_TOKEN` in
`app.js`.) Get a token at account.mapbox.com/access-tokens.

## Features

- **Globe view** (Mapbox `projection: globe`) with atmosphere/fog.
- **Layers / route selector** — switch between the four tours: Pure, +Sleep,
  +Eating, +Hurricane. Each recolors the line/points and updates the stats panel
  (distance, days, calories, closures, …) from the route's metrics JSON.
- **Play / Pause / Reset** — reveals stops in tour order, drawing the connecting
  line and (optionally) flying the camera from stop to stop.
- **Speed** (0.25–8×) and **camera zoom** sliders; toggles for camera-follow,
  the full faint route line, and all stops shown faintly.

## Notes

- Data is read live from `output/routes/`, so re-running the pipeline updates the
  app automatically (just refresh).
- ~2,000 points per route; reveal uses layer filters + line slicing (cheap), so
  it stays smooth even at 8× on the full tour.
