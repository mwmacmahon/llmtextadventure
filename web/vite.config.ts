import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The dev server answers localhost and plain IP addresses by itself. Any other host name it is reached by (a tailnet
// name, a domain behind a reverse proxy) is listed in DEV_ALLOWED_HOSTS, comma separated, in the environment or in the
// gitignored web/.env; a leading dot allows every subdomain (".example.com"). The names stay out of the repo.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const allowedHosts = (env.DEV_ALLOWED_HOSTS ?? "").split(",").map((h) => h.trim()).filter(Boolean);
  return {
    plugins: [react()],
    server: {
      host: true,
      port: 5173,
      allowedHosts,
      proxy: {
        "/api": { target: `http://127.0.0.1:${env.API_PORT ?? "8010"}`, changeOrigin: true },
      },
    },
    build: { outDir: "dist" },
  };
});
