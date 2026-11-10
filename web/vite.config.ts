import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// Built assets are served by the Python server from research_hub/ui.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  // assetsInlineLimit 0: no data: URIs, so the server can send a strict Content-Security-Policy.
  build: { outDir: "../research_hub/ui", emptyOutDir: true, sourcemap: false, assetsInlineLimit: 0 },
  server: { proxy: { "/api": "http://localhost:6230", "/blobs": "http://localhost:6230" } },
});
