import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Compiled frontend is emitted straight into the Python package so it ships
// embedded (no npm at runtime). In dev, proxy API + WebSocket to the server.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../src/kaika/webapp_dist",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8400",
      "/ws": { target: "ws://127.0.0.1:8400", ws: true },
    },
  },
});
