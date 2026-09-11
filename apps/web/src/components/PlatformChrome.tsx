import { useEffect, useRef } from "react";

import { ROUTE_BASE } from "../config";

/**
 * 挂载主站导出的站点页眉与页脚。
 *
 * 不抄一份、也不共享源码，而是加载主站构建时产出的 `/chrome/chrome.js`——
 * 那里面跑的是真正的组件（自带账号请求、积分胶囊、下拉菜单）。
 * 主站改了页眉，这里下次刷新就跟上，本仓不用重新构建。
 *
 * 内边距要自己给：主站默认 `0 4vw` / `26px 5vw` 是给整页居中布局用的，
 * 本产品左边有 248px 侧边栏，直接套会让页脚内容缩在右半边。
 */

const CHROME_JS = "/chrome/chrome.js";
const CHROME_CSS = "/chrome/chrome.css";
const MODULE_KEY = "stocks";

interface ChromeApi {
  header(selector: string, options?: { module?: string; headerPadding?: string }): void;
  footer(selector: string, options?: { footerPadding?: string }): void;
}
declare global { interface Window { XiamiChrome?: ChromeApi } }

let loading: Promise<ChromeApi | null> | null = null;

function loadChrome(): Promise<ChromeApi | null> {
  loading ??= new Promise<ChromeApi | null>((resolve) => {
    if (window.XiamiChrome) { resolve(window.XiamiChrome); return; }
    if (!document.querySelector("link[data-xm-chrome]")) {
      const link = document.createElement("link");
      link.rel = "stylesheet"; link.href = CHROME_CSS; link.dataset.xmChrome = "1";
      document.head.appendChild(link);
    }
    const script = document.createElement("script");
    script.src = CHROME_JS;
    // 取不到就整个不渲染:半塌的页眉比没有更糟,而且本产品自己的返回路径是完整的
    script.onload = () => resolve(window.XiamiChrome ?? null);
    script.onerror = () => resolve(null);
    document.head.appendChild(script);
  });
  return loading;
}

function ChromeSlot({ part, padding }: { part: "header" | "footer"; padding: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const mounted = useRef(false);
  useEffect(() => {
    if (!ROUTE_BASE || mounted.current) return;
    let live = true;
    void loadChrome().then((api) => {
      if (!live || !api || !ref.current) return;
      mounted.current = true;
      ref.current.id = `xm-chrome-${part}`;
      if (part === "header") api.header(`#xm-chrome-${part}`, { module: MODULE_KEY, headerPadding: padding });
      else api.footer(`#xm-chrome-${part}`, { footerPadding: padding });
    });
    return () => { live = false; };
  }, [part, padding]);
  if (!ROUTE_BASE) return null;
  return <div ref={ref} className={`xm-chrome-host xm-chrome-host--${part}`} />;
}

export function PlatformHeader() {
  // 用主站的默认内边距（0 4vw / 26px 5vw），几个页面才看着是一套
  return <ChromeSlot part="header" padding="" />;
}

export function PlatformFooter() {
  return <ChromeSlot part="footer" padding="" />;
}
