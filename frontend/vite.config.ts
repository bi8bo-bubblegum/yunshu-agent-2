import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: ['*'],
    cors: true,
    proxy: {
      '/api': {
        target: process.env.BACKEND_URL || 'http://localhost:8090',
        changeOrigin: true,
      },
    },
    // 让所有路径都返回 index.html（Vue Router 处理路由）
    historyApiFallback: true,
  },
})
