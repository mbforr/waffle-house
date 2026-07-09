/* Every Waffle House in America — route explorer (Mapbox GL globe).
 * Reads the pipeline's route GeoJSONs and animates the TSP tour stop-by-stop.
 *
 * Token: paste it in the UI (saved to localStorage) or hard-code below.
 * Data:  fetched from ../output/routes/ — serve the repo root over HTTP, e.g.
 *        python3 -m http.server 8000   then open  http://localhost:8000/app/
 */

const HARDCODED_TOKEN = "";          // optional: put your pk.* token here
const TOKEN_KEY = "wh_mapbox_token";
// Route data is bundled with the app (app/data) so it's self-contained and
// deployable (Vercel etc.). Refresh it from the pipeline with scripts/sync-data.sh.
const DATA_BASE = "./data";

const ROUTES = [
  { key: "pure",      label: "1 · Pure TSP",         color: "#ffb400" },
  { key: "sleep",     label: "2 · + Sleep",          color: "#3bd6c6" },
  { key: "eating",    label: "3 · + Eating",         color: "#ff6f91" },
  { key: "hurricane", label: "4 · + Hurricane (Helene)", color: "#9b8cff" },
];

const KM_MI = 0.621371;
const $ = (id) => document.getElementById(id);

// ---- token gate ----------------------------------------------------------
function getToken() {
  // Priority: config.js (from .env) -> localStorage (UI paste) -> hard-coded.
  const t = ((window.MAPBOX_TOKEN || "") || localStorage.getItem(TOKEN_KEY) ||
             HARDCODED_TOKEN || "").trim();
  return t.startsWith("pk.") ? t : "";
}
(function tokenGate() {
  const token = getToken();
  if (token) { boot(token); return; }
  $("token-gate").classList.remove("hidden");
  $("token-save").addEventListener("click", () => {
    const v = $("token-input").value.trim();
    if (!v.startsWith("pk.")) { $("token-input").focus(); return; }
    localStorage.setItem(TOKEN_KEY, v);
    location.reload();
  });
})();

// ---- main -----------------------------------------------------------------
async function boot(token) {
  mapboxgl.accessToken = token;

  // Load every route's geometry + metrics.
  let data;
  try {
    data = await loadAllRoutes();
  } catch (e) {
    $("current").innerHTML =
      `<b style="color:#ff6f91">Could not load route data.</b><br/>` +
      `Serve the repo root over HTTP and open <span class="mono">/app/</span>:<br/>` +
      `<span class="mono">python3 -m http.server 8000</span>`;
    console.error(e);
    return;
  }

  const map = new mapboxgl.Map({
    container: "map",
    style: "mapbox://styles/mapbox/dark-v11",
    projection: "globe",
    center: [-85, 34],
    zoom: 3.1,
    pitch: 0,
  });
  map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "bottom-right");

  // animation + view state
  const state = {
    routeKey: ROUTES[0].key,
    idx: -1,            // last revealed stop index (-1 = nothing yet)
    playing: false,
    timer: null,
    speed: 1,
    zoom: 5.2,
    follow: true,
  };

  map.on("style.load", () => {
    map.setFog({
      color: "rgb(10,12,16)", "high-color": "rgb(30,40,70)",
      "horizon-blend": 0.08, "space-color": "rgb(5,6,9)", "star-intensity": 0.5,
    });
    addLayers(map, data, state.routeKey);
    buildRouteSelect();
    selectRoute(state.routeKey, /*fit*/ true);
    wireControls();
  });

  // ---- layers -------------------------------------------------------------
  function addLayers(map, data, key) {
    const r = data[key];
    map.addSource("all-stops", { type: "geojson", data: r.stopsFC });
    map.addSource("full-line", { type: "geojson", data: r.lineFC });
    map.addSource("reveal-line", { type: "geojson", data: emptyLine() });
    map.addSource("closed-stops", { type: "geojson", data: r.closedFC });

    map.addLayer({
      id: "full-line", type: "line", source: "full-line",
      paint: { "line-color": r.color, "line-opacity": 0.18, "line-width": 1.2 },
      layout: { visibility: "none" },
    });
    map.addLayer({
      id: "all-stops-faint", type: "circle", source: "all-stops",
      paint: { "circle-radius": 2, "circle-color": "#5a6473", "circle-opacity": 0.5 },
    });
    map.addLayer({
      id: "reveal-line", type: "line", source: "reveal-line",
      paint: { "line-color": r.color, "line-width": 2.4, "line-opacity": 0.9 },
      layout: { "line-cap": "round", "line-join": "round" },
    });
    map.addLayer({
      id: "reveal-stops", type: "circle", source: "all-stops",
      filter: ["<=", ["get", "order"], -1],
      paint: {
        "circle-radius": 3.2, "circle-color": r.color,
        "circle-stroke-color": "#0b0d10", "circle-stroke-width": 0.6,
      },
    });
    map.addLayer({
      id: "current-stop", type: "circle", source: "all-stops",
      filter: ["==", ["get", "order"], -1],
      paint: {
        "circle-radius": 7, "circle-color": "#fff",
        "circle-stroke-color": r.color, "circle-stroke-width": 3,
      },
    });
    // Hurricane-closed stores: kept on the map, drawn red (topmost, persistent).
    map.addLayer({
      id: "closed-stops", type: "circle", source: "closed-stops",
      paint: {
        "circle-radius": 5.5, "circle-color": "#ff3b3b", "circle-opacity": 0.95,
        "circle-stroke-color": "#3a0000", "circle-stroke-width": 1.2,
      },
    });
  }

  function recolor(color) {
    for (const [id, prop] of [["full-line", "line-color"], ["reveal-line", "line-color"],
                              ["reveal-stops", "circle-color"]])
      map.setPaintProperty(id, prop, color);
    map.setPaintProperty("current-stop", "circle-stroke-color", color);
  }

  // ---- route selection ----------------------------------------------------
  function selectRoute(key, fit) {
    state.routeKey = key;
    const r = data[key];
    map.getSource("all-stops").setData(r.stopsFC);
    map.getSource("full-line").setData(r.lineFC);
    map.getSource("closed-stops").setData(r.closedFC);
    recolor(r.color);
    renderStats(r);
    reset(fit);
  }

  function reset(fit) {
    pause();
    state.idx = -1;
    map.getSource("reveal-line").setData(emptyLine());
    map.setFilter("reveal-stops", ["<=", ["get", "order"], -1]);
    map.setFilter("current-stop", ["==", ["get", "order"], -1]);
    updateProgress();
    $("current").textContent = "";
    if (fit) map.fitBounds(data[state.routeKey].bounds, { padding: 60, duration: 800 });
  }

  // ---- animation ----------------------------------------------------------
  function step() {
    const r = data[state.routeKey];
    const n = r.coords.length;          // includes closing point back to start
    if (state.idx >= n - 1) { pause(); return; }
    state.idx++;
    const i = state.idx;

    map.getSource("reveal-line").setData({
      type: "Feature", geometry: { type: "LineString", coordinates: r.coords.slice(0, i + 1) },
    });
    // points use stop "order" (0..nStops-1); the final coord closes the loop.
    const stopOrder = Math.min(i, r.nStops - 1);
    map.setFilter("reveal-stops", ["<=", ["get", "order"], stopOrder]);
    map.setFilter("current-stop", ["==", ["get", "order"], stopOrder]);

    const interval = baseInterval();
    if (state.follow) {
      map.easeTo({ center: r.coords[i], zoom: state.zoom, duration: interval * 0.85, easing: (t) => t });
    }
    updateProgress();
    const s = r.stops[stopOrder];
    if (s) $("current").innerHTML =
      `<b>#${stopOrder + 1}</b> ${s.name} — ${s.city || ""}, ${s.state || ""}`;
  }

  function baseInterval() { return Math.max(60, 320 / state.speed); }

  function tick() {
    if (!state.playing) return;
    step();
    if (state.playing) state.timer = setTimeout(tick, baseInterval());
  }
  function play() {
    const r = data[state.routeKey];
    if (state.idx >= r.coords.length - 1) reset(false);  // restart if finished
    state.playing = true;
    $("play").innerHTML = "❚❚ Pause"; $("play").classList.add("playing");
    tick();
  }
  function pause() {
    state.playing = false;
    clearTimeout(state.timer);
    $("play").innerHTML = "▶ Play"; $("play").classList.remove("playing");
  }

  function updateProgress() {
    const r = data[state.routeKey];
    const shown = Math.min(state.idx + 1, r.nStops);
    $("progress").textContent = `Stop ${shown} / ${r.nStops}`;
  }

  // ---- stats panel --------------------------------------------------------
  function renderStats(r) {
    const m = r.metrics || {};
    const km = m.total_distance_km, mi = km ? Math.round(km * KM_MI) : null;
    const rows = [];
    if (km) rows.push(`<b>${km.toLocaleString()} km</b> (${mi.toLocaleString()} mi)`);
    if (m.total_drive_time_hours)
      rows.push(`Drive: <b>${(m.total_drive_time_hours / 24).toFixed(1)} days</b>`);
    if (m.total_elapsed_hours)
      rows.push(`Elapsed: <b>${(m.total_elapsed_hours / 24).toFixed(1)} days</b>`);
    if (m.overnight_stops != null) rows.push(`Overnight stops: <b>${m.overnight_stops}</b>`);
    if (m.cumulative_calories) rows.push(`Calories: <b>${m.cumulative_calories.toLocaleString()}</b>`);
    if (m.n_closed != null)
      rows.push(`Closed by storm: <b style="color:#ff5b5b">${m.n_closed}</b> ` +
                `<span style="color:#ff5b5b">●</span> red`);
    rows.push(`Stops: <b>${r.nStops.toLocaleString()}</b>`);
    $("stats").innerHTML = rows.join("<br/>");
  }

  // ---- controls -----------------------------------------------------------
  function buildRouteSelect() {
    const sel = $("route-select");
    sel.innerHTML = ROUTES.map((r) => `<option value="${r.key}">${r.label}</option>`).join("");
  }
  function wireControls() {
    $("route-select").addEventListener("change", (e) => selectRoute(e.target.value, true));
    $("play").addEventListener("click", () => (state.playing ? pause() : play()));
    $("reset").addEventListener("click", () => reset(true));
    $("speed").addEventListener("input", (e) => {
      state.speed = +e.target.value; $("speed-label").textContent = `${state.speed}×`;
    });
    $("zoom").addEventListener("input", (e) => {
      state.zoom = +e.target.value; $("zoom-label").textContent = state.zoom.toFixed(1);
    });
    $("t-follow").addEventListener("change", (e) => (state.follow = e.target.checked));
    $("t-fullroute").addEventListener("change", (e) =>
      map.setLayoutProperty("full-line", "visibility", e.target.checked ? "visible" : "none"));
    $("t-allpoints").addEventListener("change", (e) =>
      map.setLayoutProperty("all-stops-faint", "visibility", e.target.checked ? "visible" : "none"));
  }
}

// ---- data loading ---------------------------------------------------------
async function loadAllRoutes() {
  const out = {};
  await Promise.all(ROUTES.map(async (def) => {
    const [gj, metrics] = await Promise.all([
      fetch(`${DATA_BASE}/${def.key}_tsp.geojson`).then((r) => { if (!r.ok) throw Error(r.status); return r.json(); }),
      fetch(`${DATA_BASE}/${def.key}_tsp_metrics.json`).then((r) => r.ok ? r.json() : null).catch(() => null),
    ]);
    const stops = gj.features
      .filter((f) => f.properties.kind === "stop")
      .sort((a, b) => a.properties.order - b.properties.order)
      .map((f) => ({
        order: f.properties.order, name: f.properties.name,
        city: f.properties.city, state: f.properties.state,
        lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1],
      }));
    const lineFeat = gj.features.find((f) => f.properties.kind === "route");
    const coords = lineFeat ? lineFeat.geometry.coordinates
                            : stops.map((s) => [s.lon, s.lat]);
    const closedFeats = gj.features.filter((f) => f.properties.kind === "closed");
    out[def.key] = {
      color: def.color, metrics, stops, nStops: stops.length, coords,
      nClosed: closedFeats.length,
      closedFC: { type: "FeatureCollection", features: closedFeats },
      stopsFC: { type: "FeatureCollection", features: stops.map((s) => ({
        type: "Feature", properties: { order: s.order, name: s.name, city: s.city, state: s.state },
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      })) },
      lineFC: lineFeat || { type: "Feature", geometry: { type: "LineString", coordinates: coords } },
      bounds: bbox(coords),
    };
  }));
  return out;
}

function emptyLine() { return { type: "Feature", geometry: { type: "LineString", coordinates: [] } }; }
function bbox(coords) {
  const b = coords.reduce((a, [x, y]) => [Math.min(a[0], x), Math.min(a[1], y),
    Math.max(a[2], x), Math.max(a[3], y)], [180, 90, -180, -90]);
  return [[b[0], b[1]], [b[2], b[3]]];
}
