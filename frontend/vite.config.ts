/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig(({ mode }) => {
  // The single root .env feeds the frontend too (only VITE_* variables reach the browser).
  const env = loadEnv(mode, "..", "VITE_");
  const define: Record<string, string> = {};
  for (const [k, v] of Object.entries(env)) define[`import.meta.env.${k}`] = JSON.stringify(v);

  return {
    envDir: "..",
    define,
    plugins: [
      react(),
      VitePWA({
        registerType: "autoUpdate",
        includeAssets: ["icon.svg"],
        manifest: {
          name: "SyncViewer",
          short_name: "SyncViewer",
          description: "Multi-cloud VM monitor that works offline",
          theme_color: "#0f172a",
          background_color: "#0f172a",
          display: "standalone",
          start_url: "/",
          icons: [
            { src: "icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any maskable" },
          ],
        },
        workbox: {
          // app shell is precached; API/auth calls are never cached by the service worker
          navigateFallback: "/index.html",
          globPatterns: ["**/*.{js,css,html,svg,woff2}"],
          maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        },
      }),
    ],
    build: {
      chunkSizeWarningLimit: 600, // recharts alone is ~520 kB; it is lazy-loaded with its pages
      rollupOptions: {
        output: {
          manualChunks: {
            charts: ["recharts"],
            markdown: ["react-markdown", "rehype-sanitize", "remark-gfm"],
            data: ["dexie", "dexie-react-hooks", "@supabase/supabase-js"],
          },
        },
      },
    },
    server: { port: 5173 },
    test: { environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"] },
  };
});
