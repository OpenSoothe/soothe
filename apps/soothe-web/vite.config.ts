import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      "/rpc": "http://127.0.0.1:3100",
      "/api": "http://127.0.0.1:3100",
    },
  },
});
