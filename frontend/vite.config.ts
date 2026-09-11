import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // Allow external access
    port: 5000,
    proxy: {
      // SSE endpoint — must have no timeout so long-running streams aren't dropped
      '/api/v1/sse': {
        target: 'http://localhost:9000',
        changeOrigin: true,
        ws: false,
        proxyTimeout: 0, // no timeout — SSE is a persistent stream
        timeout: 0,
      },
      // All other API routes
      '/api': {
        target: 'http://localhost:9000',
        changeOrigin: true,
        ws: true,
        proxyTimeout: 900000, // 15 minutes for long-running multi-agent runs
        timeout: 900000,
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
