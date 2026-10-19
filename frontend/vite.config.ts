import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During development the API runs separately; DESKSIDE_API points at it.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../backend/deskside/static", emptyOutDir: true },
  server: {
    proxy: { "/api": { target: process.env.DESKSIDE_API ?? "http://127.0.0.1:8080", changeOrigin: false } },
  },
});
