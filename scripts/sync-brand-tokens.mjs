/**
 * 把虾米伙伴的平台设计令牌同步进本仓。
 *
 * **为什么要落成文件而不是运行时 fetch。** 本仓的 styles.css 在构建期就要用到这些变量
 * （字号写成 calc(N * var(--xm-font-scale))）。运行时拉的话，样式表加载完成前
 * 整页字号是错的，会闪一下；而且离线/主站没起时本仓就直接构建不出来。
 *
 * **为什么落成的文件要提交进仓。** 一份干净 clone 不装主站也能构建。文件头写清楚是生成物、
 * 真源在哪，谁改了它下次同步就会被覆盖 —— 这比"忘了它是生成的、在这里改半天"要好。
 *
 * 取值优先级：
 *   1. --from=<路径>            显式指定
 *   2. 同级目录的主站仓         ../xiamimate-tools-frontend/out/chrome/tokens.css
 *   3. --origin=<https://…>     从已部署的站点取（服务器上没有源码时用这条）
 *
 * 用法：node scripts/sync-brand-tokens.mjs [--from=…] [--origin=https://xiamimate.com] [--check]
 * --check 只比对不写：CI 里用它挡住"改了主站没同步"。
 */

import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const ROOT = path.resolve(import.meta.dirname, "..");
const TARGET = path.join(ROOT, "apps", "web", "src", "brand-tokens.css");
const SIBLING = path.resolve(ROOT, "..", "xiamimate-tools-frontend", "out", "chrome", "tokens.css");

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, v] = a.replace(/^--/, "").split("=");
    return [k, v ?? true];
  }),
);

const HEADER = `/* 由 scripts/sync-brand-tokens.mjs 从虾米伙伴主站同步，勿手改。
   真源：xiamimate-tools-frontend/app/brand-tokens.css
   改动流程：改主站那一份 → 主站 npm run build → 本仓 npm run sync:tokens */
`;

async function fetchTokens() {
  if (typeof args.from === "string") return readFile(args.from, "utf8");
  if (typeof args.origin === "string") {
    const url = `${args.origin.replace(/\/$/, "")}/chrome/tokens.css`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`取 ${url} 失败：HTTP ${res.status}`);
    return res.text();
  }
  try {
    return await readFile(SIBLING, "utf8");
  } catch {
    throw new Error(
      `找不到主站导出的令牌：${SIBLING}\n` +
      "先在主站仓跑 node scripts/build-chrome-artifacts.mjs，" +
      "或用 --origin=https://xiamimate.com 从线上取。",
    );
  }
}

const incoming = HEADER + (await fetchTokens()).replace(/^\/\* 由 scripts\/build-chrome-artifacts[^\n]*\n/, "");
const current = await readFile(TARGET, "utf8").catch(() => "");

if (args.check) {
  if (current === incoming) {
    console.log("[tokens] 与主站一致 ✅");
  } else {
    console.error("[tokens] 与主站不一致 —— 跑 npm run sync:tokens 同步过来。");
    process.exit(1);
  }
} else if (current === incoming) {
  console.log("[tokens] 已是最新，未改动。");
} else {
  await writeFile(TARGET, incoming, "utf8");
  console.log(`[tokens] 已更新 ${path.relative(ROOT, TARGET)}`);
}
