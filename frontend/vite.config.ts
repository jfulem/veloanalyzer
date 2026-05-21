import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "../docs",
    emptyOutDir: false,  // preserve data.db written by Python
  },
  optimizeDeps: {
    exclude: ["sql.js"],
  },
  // sql.js needs its WASM file served as a static asset
  assetsInclude: ["**/*.wasm"],
});
