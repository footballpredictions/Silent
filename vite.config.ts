import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import pkg from './package.json'

/** Debug: фиксированный VK-хеш. Release — только через BOOTSTRAP_VK_HASH при сборке. */
const DEBUG_BOOTSTRAP_HASH = '6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY'

function resolveBootstrapVkHash(mode: string): string {
  const fromEnv = process.env.BOOTSTRAP_VK_HASH?.trim()
  if (fromEnv) return fromEnv
  return DEBUG_BOOTSTRAP_HASH
}

export default defineConfig(({ mode }) => {
  // Только явный --mode debug|development. Env DEBUG_BUILD=1 с прошлой debug-сборки
  // не должен открывать лог/хеши/капчу в release installer.
  const isDebugBuild = mode === 'debug' || mode === 'development'
  return {
  plugins: [react()],
  base: './',
  root: '.',
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __BOOTSTRAP_VK_HASH__: JSON.stringify(resolveBootstrapVkHash(mode)),
    __DEBUG_BUILD__: JSON.stringify(isDebugBuild),
  },
  build: {
    outDir: 'dist/renderer',
    sourcemap: isDebugBuild,
    charset: 'utf8',
  },
  server: {
    port: 3001,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
}})
