import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to `kiln serve` (default http://127.0.0.1:8000).
// `base` is "./" so the static build can be embedded by the Tauri desktop shell.
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
