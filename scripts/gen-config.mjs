// Build step: write app/config.js from the MAPBOX_TOKEN env var.
// Runs on Vercel (buildCommand) and locally. The token is never committed —
// config.js is gitignored; Vercel injects it from a project env var.
//
// Hardened: resolves paths from the script location (CWD-independent), creates
// app/ if missing, and never fails the deploy — a missing token just falls back
// to the in-app token prompt.
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

try {
  const token = (process.env.MAPBOX_TOKEN || "").trim();
  const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
  const appDir = join(repoRoot, "app");

  console.log(`gen-config: cwd=${process.cwd()}`);
  console.log(`gen-config: appDir=${appDir} exists=${existsSync(appDir)}`);

  mkdirSync(appDir, { recursive: true });
  const out = join(appDir, "config.js");
  writeFileSync(out,
    `// Auto-generated at build time from MAPBOX_TOKEN. Do not commit.\n` +
    `window.MAPBOX_TOKEN = ${JSON.stringify(token)};\n`);

  console.log(`gen-config: wrote ${out} — ` +
    (token.startsWith("pk.")
      ? `token set (${token.slice(0, 10)}…)`
      : "NO TOKEN. Set MAPBOX_TOKEN in Vercel → Settings → Environment Variables."));
} catch (err) {
  // Do not fail the deploy over config generation; the app can prompt for a token.
  console.error("gen-config: non-fatal error:", err && err.message ? err.message : err);
}
process.exit(0);
