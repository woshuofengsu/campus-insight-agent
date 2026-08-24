import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // naive-ui 按需引入：自动收集模板里的 n-xxx 并只打包用到的组件
    Components({
      resolvers: [NaiveUiResolver()],
      dts: false,
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      // 开发时代理 API 到 FastAPI 后端
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/web': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // 只把体积最大的 naive-ui（及其直接依赖）拆成独立 chunk，便于 immutable 缓存。
          // 注意：不要把 vue/vue-router/pinia/axios 硬归到一起——会破坏 axios 等库跨 chunk 的导出绑定。
          if (id.includes('node_modules')) {
            if (id.includes('naive-ui') || id.includes('@css-render') ||
                id.includes('@juggle') || id.includes('date-fns') ||
                id.includes('evtd') || id.includes('seemly')) {
              return 'naiveui'
            }
          }
          return undefined
        },
      },
    },
  },
})
