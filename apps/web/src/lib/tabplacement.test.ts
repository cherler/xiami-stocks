/**
 * **一块面板落在了 `{tab === "finance" && ...}` 的括号外面，于是每一个页签上都画它。**
 *
 * 2026-08-16：「钱从哪来，去了哪」那张桑基图被加在 finance 分支后面，而它前面那行
 * `</section></>}` 已经把分支收掉了。结果写下判断、待办复核、产业链……每一页
 * 底下都挂着一张一模一样的桑基图。使用者原话：「你怎么把这个模块放在了所有的
 * 公司档案 tab 页里？？！」
 *
 * ## 为什么没人发现
 *
 * 加这一块的时候只顾着往下写，**没看自己插进了哪一层括号**。而 tsc 不会响：
 * JSX 里多一块少一块都是合法的；测试也不会响：没有一条测试渲染整页。
 * 页面上的表现是"多了点东西"，而多出来的东西自己长得挺正常。
 *
 * ## 这条守卫查什么
 *
 * 每个页签专属的面板必须落在它自己那个 `{tab === "x" && ...}` 区间里。
 * 用文本位置查是够的：区间的起点是 `{tab === "x"`，终点是下一个 `{tab === `。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const APP = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");

/**
 * 某个页签分支的文本区间。
 *
 * **终点是这个分支自己的 `</>}`，不是"下一个 {tab ===="。**
 *
 * 第一版用的是后者，而那正好漏掉要守的那种形状：`</>}` 提前收了分支之后，
 * 掉在外面的面板**仍然在"下一个 {tab ==="之前** —— 也就是仍然在区间里，
 * 守卫看不见。money-flow 那次被抓到纯属侥幸（那次的改动顺手多插了一个
 * `{tab === }`，把区间缩短了）。本会话第四次踩「守卫在它要守的事上是瞎的」。
 */
function tabRange(tab: string): [number, number] {
  const start = APP.indexOf(`{tab === "${tab}" &&`);
  assert.notEqual(start, -1, `App.tsx 里找不到 {tab === "${tab}"} 分支——结构变了，这条守卫要跟着改`);
  const next = APP.indexOf("{tab === ", start + 1);
  const limit = next === -1 ? APP.length : next;
  // **最后一个 `</>}`，不是第一个。** 分支里嵌套的条件片段（`{x && <>…</>}`）
  // 也会产出 `</>}`，取第一个会把区间截得太早，把本来在里面的面板判成在外面。
  const close = APP.lastIndexOf("</>}", limit);
  return [start, close > start ? close + 4 : limit];
}

test("每个页签专属的面板都待在自己的分支里", () => {
  const owned: Array<[string, string]> = [
    ["brief", "<SchedulePanel"],
    ["finance", "<MoneyFlowPanel"],
    ["finance", "<PeerComparisonPanel"],
    ["finance", "<IndustryMetrics"],
    ["market", "<ValuationPanel"],
    ["ledger", "<AssessmentPanel"],
    ["chain", "<BusinessRelationshipClues"],
    ["research", "<Documents companyId"],
  ];
  const stray: string[] = [];
  for (const [tab, needle] of owned) {
    const [start, end] = tabRange(tab);
    const at = APP.indexOf(needle);
    assert.notEqual(at, -1, `App.tsx 里找不到 ${needle}`);
    if (at < start || at > end) stray.push(`  ${needle} 不在 {tab === "${tab}"} 分支里`);
  }
  assert.equal(stray.length, 0,
    "这些面板落在页签分支外面了，会在**每一个**页签上渲染：\n" + stray.join("\n")
    + "\n\n  → 检查它前面那行是不是提前写了 `</>}`。");
});

test("守卫本身要能红", () => {
  // 前提：区间是靠 `{tab === ` 切的。哪天改成别的写法（switch、路由表），
  // 上面那条会因为找不到分支而报错，而不是默默变绿。
  assert.ok(APP.includes('{tab === "finance" &&'), "页签的写法变了，这个文件要跟着改");
  const [start, end] = tabRange("finance");
  assert.ok(end > start && end - start < 20000, "finance 分支的区间不合理，切法失效了");
});
