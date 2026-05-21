import { defineConfig } from "vite";

export default defineConfig({
  base: "./",  // relative paths so the site works under any subdirectory (e.g. GitHub Pages /veloanalyzer/)
  build: {
    outDir: "../docs",
    emptyOutDir: false,  // preserve data.db written by Python
    rollupOptions: {
      output: {
        entryFileNames: "index.js",
        chunkFileNames: "[name].js",
        assetFileNames: "[name][extname]",
      },
    },
  },
  optimizeDeps: {
    exclude: ["sql.js"],
  },
  // sql.js needs its WASM file served as a static asset
  assetsInclude: ["**/*.wasm"],
});
