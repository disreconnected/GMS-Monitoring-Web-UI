import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
    globals: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/ws": {
        target: "ws://127.0.0.1:9847",
        ws: true,
      },
      "/api": {
        target: "http://127.0.0.1:9847",
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
