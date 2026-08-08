import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: {
      jsdom: {
        url: "http://localhost/",
      },
    },
    setupFiles: "./vitest.setup.ts",
  },
  build: {
    outDir: resolve(__dirname, "../src/openbbq/review_ui/dist"),
    emptyOutDir: true,
    sourcemap: false,
    // The review server CSP is `default-src 'self'`; inlined data: fonts would
    // be blocked, so always emit fonts as real files under /assets.
    assetsInlineLimit: (filePath) =>
      /\.(woff2?|ttf|otf)$/.test(filePath) ? false : undefined,
  },
});
