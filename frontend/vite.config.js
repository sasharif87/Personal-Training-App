/* frontend/vite.config.js */
import { defineConfig } from 'vite';

export default defineConfig({
  // Build output goes to frontend/dist (copied into Docker image for production)
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  // Dev server: proxy /api and all backend routes to FastAPI so CORS isn't an issue
  server: {
    port: 5173,
    proxy: {
      '/api':       'http://localhost:8080',
      '/status':    'http://localhost:8080',
      '/save':      'http://localhost:8080',
      '/workouts':  'http://localhost:8080',
    },
  },
});
