import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

function normalizeTarget(value) {
  if (!value) {
    return "";
  }
  return value.toString().trim().replace(/\/+$/, "");
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const proxyTarget = normalizeTarget(
    env.VITE_API_PROXY_TARGET || env.VITE_API_BASE || "",
  );
  return {
    plugins: [vue()],
    server: proxyTarget
      ? {
          proxy: {
            "/api": {
              target: proxyTarget,
              changeOrigin: true,
            },
            "/outputs": {
              target: proxyTarget,
              changeOrigin: true,
            },
          },
        }
      : undefined,
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
  };
});
