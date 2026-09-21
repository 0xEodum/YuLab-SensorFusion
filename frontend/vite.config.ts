import path from "path";
import { fileURLToPath } from "url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const backendPort = Number(process.env.YULAB_BACKEND_PORT || 8000);
if (!Number.isInteger(backendPort) || backendPort < 1 || backendPort > 65535) {
  throw new Error('YULAB_BACKEND_PORT must be a TCP port number');
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), viteSingleFile()],
  server: {
    host: '127.0.0.1',
    proxy: { '/api': `http://127.0.0.1:${backendPort}` },
  },
  preview: {
    host: '127.0.0.1',
    proxy: { '/api': `http://127.0.0.1:${backendPort}` },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});
