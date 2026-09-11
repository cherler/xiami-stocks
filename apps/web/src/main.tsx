import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { ErrorBoundary } from "./ErrorBoundary";
import { watchVitals } from "./lib/vitals";
import "./styles.css";

// 真实用户监测：只发几个毫秒数、页面名和设备大类，收进自己的库。
// 页面名从 pathname 推——**不带查询串**，那里可能有搜索词。
watchVitals(() => {
  const path = window.location.pathname.replace(/^.*\/stocks/, "") || "/";
  const first = path.split("/").filter(Boolean)[0] || "dashboard";
  return first;
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
