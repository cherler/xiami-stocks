/**
 * 窄屏下不许出现「页面能左右拖」和「浮层跑到屏幕外」。
 *
 * 2026-08-19 全站巡检，390×844（手机常见尺寸）逐页量了一遍：
 *
 * · /screener —— 「换个排法」那个 select 的固有宽度来自最长的选项，
 *   被撑到 405px，把整页顶成 433px。页面本身能左右拖，
 *   而这个仓的规矩是：宽内容只在自己的容器里滚，body 永远不横向滚。
 * · /portfolio —— 「高级记录」浮层里三个按钮排在 324→450px，一半在屏幕外。
 *   根因是 `@media (max-width: 620px)` 里把它从 `right: 0` 改成了 `left: 0`，
 *   而这个菜单挂在标题栏**右侧** —— 按左边缘对齐等于把浮层整个往右推。
 *
 * 深色模式那一遍 15 个页面全干净，所以这里只盯窄屏这一类。
 *
 * 这里测的是源码：真实布局要跑浏览器，而门禁里没有浏览器
 * （冒烟测试是另一层，见 scripts/smoke.mjs）。结构测不了像素，
 * 但能拦住"把浮层改回左对齐"和"把 max-width 删掉"这两种回归。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const CSS = readFileSync(join(import.meta.dirname, "..", "styles.css"), "utf8");

/** 取出某个选择器最后一次出现时的那条声明。 */
function ruleFor(selector: string): string {
  const at = CSS.lastIndexOf(selector + " {");
  assert.notEqual(at, -1, `styles.css 里找不到 ${selector} —— 改名了就把这条测试一起改`);
  return CSS.slice(at, CSS.indexOf("}", at));
}

test("高级记录浮层挂在右边，不许改回左对齐", () => {
  // **看最后一条 —— 层叠里赢的是它。** 第一版按 @media 的位置去截，
  // 而文件里有好几个 max-width 媒体查询，截错了块，红在一个已经改好的地方。
  const rule = ruleFor(".portfolio-advanced-actions");
  assert.match(rule, /right:\s*0/,
    "浮层没有右对齐 —— 它挂在标题栏右侧，左对齐会把按钮推到屏幕外（实测 390px 下三个按钮排到 450px）");
  assert.doesNotMatch(rule, /left:\s*0/, "又改回左对齐了");
  assert.match(rule, /max-width:/, "没有夹 max-width，窄到极限还是会顶出去");
});

test("深舱里的下拉要能缩", () => {
  // select 的固有宽度来自最长选项，flex 子项默认又不肯缩到内容以下。
  const label = ruleFor(".deck-select");
  assert.match(label, /min-width:\s*0/, ".deck-select 没有 min-width:0，flex 子项不会缩");
  assert.match(label, /max-width:\s*100%/, ".deck-select 没有 max-width");
  assert.match(ruleFor(".deck-select select"), /max-width:\s*100%/,
    "select 自己也要夹住 —— 它的固有宽度来自最长的那个选项");
});
