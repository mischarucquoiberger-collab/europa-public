import { dirname, resolve } from 'path'
import { fileURLToPath } from 'url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'
import uiOnlyWorkspace from './dev/uiOnlyWorkspace.js'

const configDir = dirname(fileURLToPath(import.meta.url))
const env = loadEnv(process.env.NODE_ENV ?? 'development', configDir, '')
const backendOrigin = env.BACKEND_ORIGIN
// Callisto research desk (LECTIO/callisto, backend/workspace_bridge.py): answers the workspace chat
// and the price card's history; streamed answers (SSE) pass through unbuffered.
const callistoOrigin = env.CALLISTO_ORIGIN || 'http://127.0.0.1:8140'
const callistoProxy = { target: callistoOrigin, changeOrigin: true, ws: false, timeout: 0, proxyTimeout: 0 }

// https://vite.dev/config/
export default defineConfig({
  logLevel: 'error', // Suppress warnings, only show errors
  resolve: {
    alias: {
      '@': resolve(configDir, './src'),
    },
  },
  server: {
    port: 3000,
    // The app is deliberately local-only. Accept only loopback development
    // hostnames so DNS-rebinding cannot reach Vite through an arbitrary Host.
    allowedHosts: ['localhost', '127.0.0.1', '::1'],
    // Optional same-origin proxy to the report API (see .env.example).
    proxy: {
      '/xyz/api/agents/chat': callistoProxy,
      '^/xyz/api/(convos|messages)(/|\\?|$)': callistoProxy,
      '^/api/price-history/': callistoProxy,
      ...(backendOrigin ? {
      '/api': { target: backendOrigin, changeOrigin: true },
      // The report routes are not under /api. Same origin on purpose: the report viewer
      // reads the report frame's document.
      '^/(start|status|jobs|download)(/|\\?|$)': { target: backendOrigin, changeOrigin: true },
      } : {}),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Stable vendor chunk: React and the router change only on a dependency
        // bump, so an app-only build keeps this file's hash.
        manualChunks(id) {
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/.test(id)) return 'vendor-react'
          return undefined
        },
      },
    },
  },
  // uiOnlyWorkspace: serves the built Deep Research workspace (public/xyz) with fixed start-up
  // answers, so its real screen opens after the splash without any research service.
  plugins: [react(), uiOnlyWorkspace()],
})
