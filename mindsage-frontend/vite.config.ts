import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

const manualChunkGroups: Record<string, string[]> = {
  react: ['react', 'react-dom', 'react-router-dom'],
  query: ['@tanstack/react-query'],
  ui: ['framer-motion', '@radix-ui/react-dialog', '@radix-ui/react-dropdown-menu', '@radix-ui/react-tooltip'],
  reactflow: ['@xyflow/react'],
};

const manualChunks = (id: string) => {
  if (!id.includes('/node_modules/')) {
    return undefined;
  }

  for (const [chunkName, dependencies] of Object.entries(manualChunkGroups)) {
    if (dependencies.some((dependency) => id.includes(`/node_modules/${dependency}/`))) {
      return chunkName;
    }
  }

  return undefined;
};

// https://vitejs.dev/config/
export default defineConfig(() => ({
  server: {
    host: "::",
    port: 8080,
    allowedHosts: true,
    hmr: {
      overlay: false,
    },
    proxy: {
      '/api': {
        target: 'http://localhost:3003',
        changeOrigin: true,
      },
    },
    watch: {
      ignored: ['**/vector-store/.venv/**', '**/node_modules/**'],
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    target: 'esnext', // Support top-level await for noVNC
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
    chunkSizeWarningLimit: 500,
  },
  esbuild: {
    target: 'esnext', // Support top-level await for noVNC
  },
  optimizeDeps: {
    exclude: ['@novnc/novnc'],
  },
}));
