import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 前端通过 /api 相对路径访问后端；dev/preview 由 vite 代理转发到后端服务。
// 换后端地址（例如阿里云 ECS）时改 web/.env.development 里的 VITE_API_PROXY_TARGET，
// 或完全不改这里，直接把 VITE_API_BASE_URL 指到后端绝对地址（后端已开 CORS）。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_PROXY_TARGET || 'http://localhost:8000'
  const proxy = {
    '/api': { target, changeOrigin: true },
  }

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy,
    },
    preview: {
      port: 4173,
      proxy,
    },
  }
})
