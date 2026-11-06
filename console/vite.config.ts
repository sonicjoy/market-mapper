import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Local-only IAP stand-in (real IAP injects this in deploy).
const DEV_OPERATOR = process.env.MAPPING_CP_DEV_EMAIL ?? "joe.luo@whiteswandata.com";
const API_PORT = process.env.MAPPING_CP_API_PORT ?? "8001";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: true },
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${API_PORT}`,
        changeOrigin: true,
        timeout: 0,
        proxyTimeout: 0,
        rewrite: (path) => path.replace(/^\/api/, ""),
        headers: {
          "X-Goog-Authenticated-User-Email": `accounts.google.com:${DEV_OPERATOR}`,
        },
      },
    },
  },
});
