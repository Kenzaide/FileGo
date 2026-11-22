import { defineConfig } from 'vite';

// The browser always calls relative /api. In development Vite forwards it to the Flask server,
// so the page works from the laptop or from a phone (http://<laptop-ip>:5173) without CORS.
const target = process.env.VITE_API_PROXY || 'http://localhost:5000';

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: { '/api': { target, changeOrigin: false } },
  },
  preview: {
    host: '0.0.0.0',
    proxy: { '/api': { target, changeOrigin: false } },
  },
});
