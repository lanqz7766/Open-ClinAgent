import path from "node:path"

import react from "@vitejs/plugin-react"
import { viteCommonjs } from "@originjs/vite-plugin-commonjs"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

export default defineConfig({
  base: "/demo-static/",
  plugins: [react(), viteCommonjs(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  optimizeDeps: {
    exclude: [
      "@cornerstonejs/dicom-image-loader",
      "@cornerstonejs/polymorphic-segmentation",
      "@icr/polyseg-wasm",
    ],
    include: ["dicom-parser"],
  },
  worker: {
    format: "es",
    rollupOptions: {
      external: ["@icr/polyseg-wasm"],
    },
  },
  build: {
    outDir: "../src/clinagent/ui/demo-next",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // Preserve the browser-facing host for the gateway's same-origin checks.
      "/api": { target: "http://127.0.0.1:3000", changeOrigin: false },
      "/health": { target: "http://127.0.0.1:3000", changeOrigin: false },
    },
  },
})
