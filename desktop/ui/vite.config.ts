import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Tauri 通过 tauri.conf.json 的 frontendDist 直接加载 ../ui/dist 的静态产物，
// 因此 base 必须是相对路径，否则资源会按 http:// 根路径解析而 404。
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
  },
})
