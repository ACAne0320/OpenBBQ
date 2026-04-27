import react from "@vitejs/plugin-react";
import { defineConfig, type UserConfig } from "vite";

type VitestConfig = UserConfig & {
  test: {
    environment: "jsdom";
    globals: boolean;
    setupFiles: string[];
  };
};

const config: VitestConfig = {
  plugins: [react()],
  resolve: {
    alias: {
      "@": "/src"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: []
  }
};

export default defineConfig(config);
