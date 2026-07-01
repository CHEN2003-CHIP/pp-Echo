import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  root,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(root, "src")
    }
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        ws: true,
        changeOrigin: true
      }
    }
  }
});
