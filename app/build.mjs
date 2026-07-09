// Vercel build step — runs with app/ as the project root (Root Directory = app).
// Writes config.js from the MAPBOX_TOKEN env var. The token is never committed
// (config.js is gitignored); Vercel injects it from a project env var.
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const token = (process.env.MAPBOX_TOKEN || "").trim();
const out = fileURLToPath(new URL("./config.js", import.meta.url));
writeFileSync(out,
  `// Auto-generated at build time from MAPBOX_TOKEN. Do not commit.\n` +
  `window.MAPBOX_TOKEN = ${JSON.stringify(token)};\n`);

console.log(token.startsWith("pk.")
  ? `build: wrote config.js (token ${token.slice(0, 10)}…)`
  : "build: wrote config.js WITHOUT a token — set MAPBOX_TOKEN in " +
    "Vercel → Settings → Environment Variables.");
