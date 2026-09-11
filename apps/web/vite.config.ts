import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// 挂在主站子路径下时要设 base，否则 _next 之外的资源路径会指向域名根。
// 线上：VITE_BASE=/stocks/  本机：留空即 /
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");
  return {
  base: env.VITE_BASE || "/",
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ["echarts/core", "echarts/components", "echarts/charts", "echarts/renderers"],
          react: ["react", "react-dom"],
        },
      },
    },
  },
  server: {
    // **显式绑 127.0.0.1。** 不写的话 Vite 只监听 IPv6 的 [::1]，
    // 而本地网关（以及大多数脚本、健康检查）连的是 IPv4 的 127.0.0.1 ——
    // 于是 Vite 明明在跑，网关那边却是「连接被拒绝」，
    // 现象是「从主站点进虾米看股一片空白」，查半天查不到原因。
    host: "127.0.0.1",
    port: 5217,
    strictPort: true,
    // **HMR 直连 Vite，不跟着页面的来源走。**
    //
    // 页面可能是从别的源送过来的（主站 dev :3000 的 rewrite、本地网关 :8090），
    // 而 Vite 默认让浏览器按「当前页面的源」去连 HMR —— 于是 WebSocket 升级
    // 要穿过那一层代理。穿不过去时它每秒重连一次、每次挂住一条连接；
    // 浏览器对同一主机只有 6 条并发，六条占满之后**点击、跳转、接口全排队**，
    // 表现是「页面好好的，但按什么都卡半天」（实测 10s 超时）。
    //
    // 写死 clientPort 之后，浏览器无论从哪个源拿到页面都直接连 5217，
    // 代理那一层从此只管普通 HTTP。
    hmr: { host: "127.0.0.1", clientPort: 5217, protocol: "ws" },
    proxy: {
      "/api": "http://127.0.0.1:8108",
      "/health": "http://127.0.0.1:8108",
    },
  },
  };
});
