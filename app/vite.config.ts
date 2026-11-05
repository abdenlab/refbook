import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import { catalogHandler } from "./server/catalog.ts";

// The catalog served at /catalog/ in development: the repository's build, or
// REFBOOK_CATALOG. The app reads VITE_CATALOG_URL (default /catalog/), so a
// deployed build points at a published release instead.
const catalogDir = process.env.REFBOOK_CATALOG ?? fileURLToPath(new URL("../catalog/output/build/grch38", import.meta.url));

function serveCatalog(): Plugin {
  const handler = catalogHandler(catalogDir);
  return {
    name: "refbook-catalog",
    configureServer(server) { server.middlewares.use("/catalog", handler); },
    configurePreviewServer(server) { server.middlewares.use("/catalog", handler); },
  };
}

export default defineConfig({
  plugins: [serveCatalog()],
  optimizeDeps: { exclude: ["@abdenlab/refbook"] },
  server: { fs: { allow: [".", "../js"] } },
  build: { target: "es2022" },
});
