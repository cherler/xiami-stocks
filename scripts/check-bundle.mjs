/**
 * 首屏预算。**构建之后跑，超了就炸。**
 *
 *   node scripts/check-bundle.mjs            # 默认看 apps/web/dist
 *
 * ## 为什么要有预算
 *
 * 2026-08-13 实测：公司列表、研究任务、设置、我的判断——这四页一张图都没有，
 * 却每次都要先下 626 kB 的 echarts 才开始渲染。原因是驾驶舱
 * （`MarketCockpit`，唯一一个直接 import 的图表组件）把它拽进了首屏包。
 * 改成懒加载之后这四页从 1716 kB 降到 1071 kB。
 *
 * 这种事**会自己长回来**：以后任何人在 App.tsx 顶部直接 import 一个画图的组件，
 * 首屏又会多出来六百多 kB，而页面看着一切正常，只是慢。所以要有一道机械的闸：
 *
 * 1. 图表包不许出现在首屏依赖里（`index.html` 的 modulepreload 名单）；
 * 2. 入口 chunk 不许超过预算。
 *
 * 预算不是拍脑袋：取当前值 + 10% 的余量。**它该随着优化往下调，不该往上抬** ——
 * 真要抬，先在这里写清楚为什么。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { argv, exit } from "node:process";

const dist = argv[2] || "apps/web/dist";
const ENTRY_BUDGET_KB = 560;      // 当前 494 kB（2026-08-13）
const CSS_BUDGET_KB = 320;        // 当前 290 kB
/** 这些包一律不许进首屏：它们只服务于某几屏，其余页面下了纯属白等。 */
const LAZY_ONLY = ["charts-"];

let html;
try {
  html = readFileSync(join(dist, "index.html"), "utf8");
} catch {
  console.error(`读不到 ${dist}/index.html —— 先构建再跑：VITE_BASE=/stocks/ npm run build`);
  exit(1);
}

// 首屏依赖 = index.html 里直接引的 script + 它列出的 modulepreload
const firstLoad = [...html.matchAll(/(?:src|href)="([^"]+\.(?:js|css))"/g)].map((m) => m[1].split("/").pop());
const problems = [];

for (const prefix of LAZY_ONLY) {
  const leaked = firstLoad.filter((name) => name.startsWith(prefix));
  if (leaked.length) {
    problems.push(`${leaked.join("、")} 跑进了首屏依赖 —— 它应该只在用得上的那一屏才加载。\n`
      + "    多半是有人在 App.tsx 顶部直接 import 了一个画图的组件；改成 lazy(() => import(...))。");
  }
}

const sizeOf = (name) => statSync(join(dist, "assets", name)).size / 1024;
const assets = readdirSync(join(dist, "assets"));
const entry = firstLoad.find((name) => /^index-.*\.js$/.test(name)) || assets.find((n) => /^index-.*\.js$/.test(n));
const css = firstLoad.find((name) => /\.css$/.test(name)) || assets.find((n) => /\.css$/.test(n));

if (entry && sizeOf(entry) > ENTRY_BUDGET_KB) {
  problems.push(`入口 ${entry} 是 ${sizeOf(entry).toFixed(0)} kB，超过预算 ${ENTRY_BUDGET_KB} kB`);
}
if (css && sizeOf(css) > CSS_BUDGET_KB) {
  problems.push(`样式 ${css} 是 ${sizeOf(css).toFixed(0)} kB，超过预算 ${CSS_BUDGET_KB} kB`);
}

console.log(`首屏依赖（${dist}）：`);
for (const name of firstLoad) {
  let size = "";
  try { size = `${sizeOf(name).toFixed(0)} kB`; } catch { size = "（外部）"; }
  console.log(`  ${size.padStart(9)}  ${name}`);
}

if (problems.length) {
  console.error("\n✗ 首屏预算没过：\n  - " + problems.join("\n  - "));
  exit(1);
}
console.log(`\n✓ 首屏预算通过（入口 ≤ ${ENTRY_BUDGET_KB} kB、样式 ≤ ${CSS_BUDGET_KB} kB、图表包不在首屏）`);
