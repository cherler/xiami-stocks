/**
 * 点了没反应，是这个前端最贵的一类 bug。
 *
 * 一个异步动作失败之后，如果没人接住错误，用户看到的是：按钮转完就停、
 * 数据没变、页面上一个字都没有。**这跟"成功了但没刷新"长得一模一样**，
 * 而两者该做的事完全相反（重试 vs 别重试）。
 *
 * 2026-08-19 全站巡检一次撞到三处：
 * · 首页「同步实时行情」——`refreshMarket()` 抛出后没人接，成了未捕获的
 *   Promise 拒绝（那次是 20 秒超时掐掉了一个 25 秒才回来的成功请求）；
 * · 「删除这笔」交易 —— 只有 try/finally，删失败时那一笔还在列表里；
 * · 两处轮询在**页面打开时接上一个还在跑的任务**这条路径上写的是
 *   `.catch(() => undefined)` —— 吞掉之后连 setRunning(false) 都执行不到，
 *   按钮永远停在「正在…」。点按钮那条路径本来就是对的，只有这条漏了，
 *   而它恰恰是刷新页面之后必走的一条。
 *
 * 这里测的是源码结构：App.tsx 太大、又依赖 Vite 的 import.meta.env，
 * 在 node --test 里 import 不进来。结构测不了"错误文案对不对"，
 * 但能拦住"整段没有 catch"和"catch 了却什么都不做"这两种。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const APP = readFileSync(join(import.meta.dirname, "..", "App.tsx"), "utf8");

/** 取出一个 `async function 名字(...) { ... }` 的函数体，按大括号配平。 */
function bodyOf(name: string): string {
  const at = APP.indexOf(`async function ${name}(`);
  assert.notEqual(at, -1, `App.tsx 里找不到 ${name}() —— 改名了就把这条测试一起改`);
  let i = APP.indexOf("{", at), depth = 0, j = i;
  for (; j < APP.length; j += 1) {
    if (APP[j] === "{") depth += 1;
    else if (APP[j] === "}" && --depth === 0) break;
  }
  return APP.slice(i, j);
}

test("同步行情失败要落到页面上，不是变成未捕获的拒绝", () => {
  const body = bodyOf("syncMarket");
  assert.match(body, /catch\s*\(/, "syncMarket 没有 catch —— 失败时页面上一个字都没有");
  assert.match(body, /setMarketError\(/, "接住了但没往任何地方写，等于还是没提示");
  // 它现在是后台任务：起完就返回，进度靠轮。**任务失败也要报出来** ——
  // 后台任务的失败原因落在任务表里，不读它就等于又回到"点了没反应"。
  assert.match(body, /"失败"|已中断/, "任务失败时没有读任务表里的原因");
  // 轮询要有尽头：没有上限的话，任务那头没了消息，按钮就永远停在「正在同步…」。
  assert.match(body, /attempt < \d+/, "轮询没有上限");
  // 光有 state 没渲染也白搭。
  assert.match(APP, /\{marketError && <p className="form-error">\{marketError\}<\/p>\}/,
    "marketError 没有被渲染出来");
});

test("删一笔交易失败要说出来", () => {
  const body = bodyOf("remove");
  assert.match(body, /catch\s*\(/, "删除失败时那一笔还在列表里，而页面什么都不说");
  assert.match(body, /setRemoveError\(/);
  assert.match(APP, /\{removeError && <p className="form-error">\{removeError\}<\/p>\}/);
});

test("轮询的错误不许吞掉 —— 吞了按钮就永远停在「正在…」", () => {
  // `.catch(() => undefined)` 之所以致命，是因为 poll() 里的 setRunning(false)
  // 在抛出点之后，根本执行不到。
  const swallowed = [...APP.matchAll(/void\s+poll\w*\([^)]*\)\s*\.catch\(\(\)\s*=>\s*undefined\)/g)];
  assert.deepEqual(swallowed.map((m) => m[0]), [],
    "这些轮询把错误吞了，出错时按钮会永远转圈：\n  " + swallowed.map((m) => m[0]).join("\n  "));
});

test("轮询接住错误之后要把「正在…」也关掉", () => {
  // 只 setError 不 setRunning(false)，按钮照样卡着，只是旁边多了行红字。
  for (const m of APP.matchAll(/void\s+(poll\w*)\([^)]*\)\s*\.catch\(\(caught\)\s*=>\s*\{([^}]*)\}/g)) {
    assert.match(m[2], /setRunning\(false\)/,
      `${m[1]} 的 catch 里没有 setRunning(false) —— 报了错按钮还在转`);
  }
});
