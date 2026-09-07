import { existsSync } from "node:fs";
import { cpSync, mkdirSync, readdirSync } from "node:fs";
import path from "node:path";

const webDist = path.resolve(import.meta.dirname, "..", "..", "soothe-web", "dist");
const srcDir = path.resolve(import.meta.dirname, "..", "src");
const outDir = path.resolve(import.meta.dirname, "..", "dist");

mkdirSync(outDir, { recursive: true });

// Copy web dist (production build of the React UI)
if (existsSync(webDist)) {
  cpSync(webDist, path.join(outDir, "web"), { recursive: true });
  console.log("Copied web dist to dist/web");
} else {
  console.warn("Web dist not found at", webDist, "— run pnpm --filter @soothe/web build first");
}

// Copy static HTML/CSS/JS from src/ that tsc doesn't emit
for (const file of readdirSync(srcDir)) {
  if (file.endsWith(".html") || file.endsWith(".css") || file.endsWith(".js") || file.endsWith(".cjs")) {
    cpSync(path.join(srcDir, file), path.join(outDir, file));
    console.log(`Copied ${file} to dist/`);
  }
}
