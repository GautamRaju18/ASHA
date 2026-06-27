import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During dev, proxy /api to the FastAPI backend on :8000.
// In production, FastAPI serves the built bundle, so /api is same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    // keep the bundle lean for rural bandwidth; lazy-load the map chunk
    chunkSizeWarningLimit: 900,
  },
});
