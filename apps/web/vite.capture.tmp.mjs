// 录屏专用的临时配置：跟仓库里那份唯一的区别是接口指向 8109（STOCK_ACCESS=open）。
// 放在 job 目录里，不进仓库。
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  root: "/Users/liuzhenhai/projects/xiamimate/xiamimate-stock-lab/apps/web",
  base: "/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 4177,
    strictPort: true,
    hmr: false,                       // 录屏不需要热更新，少一条会重连的 WebSocket
    proxy: {
      "/api": "http://127.0.0.1:8109",
      "/health": "http://127.0.0.1:8109",
    },
  },
});
