import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const root = import.meta.dirname

// 纯静态看板：数据以相对 JSON 导入（dev 热更新，build 内联），无后端、无 fetch。
export default defineConfig({
  // GitHub Pages 项目站点：仓库名决定路径前缀。相对基址让产物在
  // /OmniNexus/ 子路径、本地 file:// 预览与 dev 下都能正确解析。
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(root, './src'),
    },
  },
  server: {
    port: 5173,
    // 允许读取仓库根目录下的 data/ 与 chains/（看板只读，绝不写回）
    fs: {
      allow: [path.resolve(root, '..')],
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
