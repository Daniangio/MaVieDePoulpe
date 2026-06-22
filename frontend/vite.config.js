import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import fs from "fs";

const repoRoot = path.resolve(__dirname, "..");
const envDir = fs.existsSync(path.join(repoRoot, ".env")) ? repoRoot : __dirname;

export default defineConfig({
  envDir,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    watch: {
      usePolling: true,
      ignored: ["**/node_modules/**", "**/dist/**", "**/vite.config.js"],
    },
    proxy: {
      "/api": {
        target: "http://backend:8000",
        changeOrigin: true,
        ws: true,
      },
      "/static": {
        target: "http://backend:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://backend:8000",
        ws: true,
        changeOrigin: true,
      },
    },
    host: "0.0.0.0",
  },
});
