import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const root = import.meta.dirname

// 纯静态看板：数据以相对 JSON 导入（dev 热更新，build 内联），无后端、无 fetch。
export default defineConfig({
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
