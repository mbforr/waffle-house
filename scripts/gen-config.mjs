// Build step: write app/config.js from the MAPBOX_TOKEN env var.
// Runs on Vercel (buildCommand) and can be run locally too. The token is never
// committed — config.js is gitignored; Vercel injects it from a project env var.
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const token = (process.env.MAPBOX_TOKEN || "").trim();
const out = fileURLToPath(new URL("../app/config.js", import.meta.url));

writeFileSync(out,
  `// Auto-generated at build time from MAPBOX_TOKEN. Do not commit.\n` +
  `window.MAPBOX_TOKEN = ${JSON.stringify(token)};\n`);

if (token.startsWith("pk.")) {
  console.log(`gen-config: wrote ${out} (token ${token.slice(0, 10)}…)`);
} else {
  console.warn("gen-config: MAPBOX_TOKEN missing/invalid — app will show the " +
               "token prompt. Set it in Vercel → Project → Settings → Environment Variables.");
}
