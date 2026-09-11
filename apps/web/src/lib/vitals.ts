/**
 * 真实用户监测：他们那边多快、有没有报错。**自建，不引第三方 SDK。**
 *
 * ## 为什么不接 Sentry / GA 之类
 *
 * 这个应用的页面上全是持仓成本、买卖理由、还没公开的判断。第三方 SDK 默认会抓
 * 面包屑、DOM 文本、完整 URL —— 那等于把研究记录发出去。所以这里只发四个毫秒数、
 * 一个页面名和设备大类，收进自己的库（服务端还会按白名单再校一遍页面名）。
 *
 * ## 为什么不引 web-vitals 库
 *
 * 它能多给 INP/CLS，但要多一个依赖进首屏包 —— 而我们刚把首屏从 1716 kB
 * 压到 1071 kB。原生的 PerformanceObserver 已经能拿到 LCP 和导航计时，
 * 够回答"哪一页慢、优化有没有用"这两个问题。真需要 INP 时再单独懒加载。
 *
 * ## 什么时候发
 *
 * 页面进入后台（visibilitychange → hidden）时用 sendBeacon 发一次。
 * **不在 load 时发**：那时 LCP 还可能没定；也**不用 fetch**：页面正在关闭，
 * fetch 会被浏览器掐掉，sendBeacon 是专门为这一刻设计的。
 */

import { apiUrl } from "../config";

type Sample = {
  page: string;
  kind: "nav" | "error";
  ttfb_ms?: number | null;
  dom_ready_ms?: number | null;
  load_ms?: number | null;
  lcp_ms?: number | null;
  error_name?: string;
  error_message?: string;
  device: string;
};

function device(): string {
  const ua = navigator.userAgent;
  if (/iPad|Tablet/i.test(ua)) return "tablet";
  if (/Mobi|Android|iPhone/i.test(ua)) return "mobile";
  return "desktop";
}

function send(sample: Sample): void {
  try {
    const body = JSON.stringify(sample);
    // sendBeacon 在页面关闭时也送得出去；不支持就退回 keepalive fetch。
    if (navigator.sendBeacon) {
      navigator.sendBeacon(apiUrl("/api/v1/rum"), new Blob([body], { type: "application/json" }));
      return;
    }
    void fetch(apiUrl("/api/v1/rum"), {
      method: "POST", body, keepalive: true, headers: { "Content-Type": "application/json" },
    }).catch(() => undefined);
  } catch {
    // 监测坏了不能影响页面。**这一层永远不许抛。**
  }
}

let lcp: number | null = null;
let reported = false;

/** 挂一次就够（在 main.tsx 里）。`currentPage` 让调用方告诉我们现在是哪一屏。 */
export function watchVitals(currentPage: () => string): void {
  if (typeof window === "undefined" || !("PerformanceObserver" in window)) return;

  try {
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) lcp = Math.round(entry.startTime);
    });
    observer.observe({ type: "largest-contentful-paint", buffered: true });
  } catch {
    // 老浏览器不支持这个 type，直接算了——没有 LCP 也还有导航计时
  }

  // JS 报错：只留类型和消息前 200 字。**不留堆栈**——堆栈里会带上变量与 URL。
  window.addEventListener("error", (event) => {
    send({ page: currentPage(), kind: "error", device: device(),
           error_name: event.error?.name || "Error", error_message: String(event.message || "").slice(0, 200) });
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    send({ page: currentPage(), kind: "error", device: device(),
           error_name: reason?.name || "UnhandledRejection",
           error_message: String(reason?.message || reason || "").slice(0, 200) });
  });

  const reportNavigation = () => {
    if (reported) return;
    reported = true;
    const nav = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    send({
      page: currentPage(),
      kind: "nav",
      device: device(),
      ttfb_ms: nav ? Math.round(nav.responseStart) : null,
      dom_ready_ms: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
      load_ms: nav ? Math.round(nav.loadEventEnd || nav.duration) : null,
      lcp_ms: lcp,
    });
  };

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") reportNavigation();
  });
  // 有些浏览器（尤其是被直接关掉的标签页）不一定给 visibilitychange，pagehide 兜底。
  window.addEventListener("pagehide", reportNavigation);
}
