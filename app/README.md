# Waffle House Route Explorer (Mapbox globe)

Interactive globe app that animates the TSP tours produced by the pipeline.
Self-contained: route data is bundled in `app/data/`, so it runs locally and
deploys as a static site.

## Run locally

```bash
cd app
python3 -m http.server 8000
# open http://localhost:8000/
```

The Mapbox token is read from `config.js` (gitignored). Locally, generate it
from the repo-root `.env`:

```bash
( cd app && MAPBOX_TOKEN="$(grep '^MAPBOX_TOKEN=' ../.env | cut -d= -f2-)" node build.mjs )
```

(You can also paste a token into the in-app prompt — it's saved to localStorage —
or hard-code `HARDCODED_TOKEN` in `app.js`.)

## Deploy to Vercel

This `app/` folder is the deployable unit. In the Vercel project set
**Root Directory = `app`**, and the token comes from an **environment variable**
(never committed).

1. Import the repo at vercel.com (or run `vercel`).
2. Project → Settings → **Root Directory → `app`**.
3. Project → Settings → **Environment Variables** → add
   `MAPBOX_TOKEN = pk.…` (Production + Preview + Development).
4. Deploy. `app/vercel.json` runs `node build.mjs`, which writes `config.js`
   from `MAPBOX_TOKEN`, then serves this folder.

`app/vercel.json`:
```json
{ "buildCommand": "node build.mjs", "outputDirectory": ".", "framework": null }
```

> **Restrict the token.** A Mapbox `pk.*` token is visible in client-side JS by
> design. In Mapbox → Account → Tokens, add a **URL restriction** for your Vercel
> domain so it can't be reused elsewhere.

## Keep data fresh

`app/data/` is a committed snapshot of the route GeoJSONs. After re-running the
TSP solvers, refresh it:

```bash
scripts/sync-data.sh      # copies output/routes/*.{geojson,json} -> app/data/
```

## Features

- **Globe view** (Mapbox `projection: globe`) with atmosphere/fog.
- **Route selector** — Pure, +Sleep, +Eating, +Hurricane. Recolors line/points
  and updates the stats panel (distance, days, calories, closures) from metrics.
- **Hurricane view** shows the 24 storm-closed stores as persistent **red** dots
  (kept on the map, not removed) while the tour reroutes around them.
- **Play / Pause / Reset** — reveals stops in tour order, drawing the line and
  flying the camera stop-to-stop.
- **Speed** (0.25–8×), **camera zoom**, and toggles for camera-follow, the faint
  full route line, and all stops shown faintly.
