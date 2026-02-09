import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // Allow external access
    port: 5000,
    proxy: {
      // HTTP API proxy
      '/api': {
        target: 'http://localhost:9000',
        changeOrigin: true,
        ws: true, // Enable WebSocket proxying for all /api routes
        configure: (proxy, _options) => {
          proxy.on('error', (err, _req, _res) => {
            console.log('proxy error', err);
          });
          proxy.on('proxyReq', (_proxyReq, req, _res) => {
            console.log('Proxying:', req.method, req.url);
          });
          proxy.on('proxyReqWs', (_proxyReq, req, _socket, _options, _head) => {
            console.log('Proxying WebSocket:', req.url);
          });
        },
      },
    },
  },
})
