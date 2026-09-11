/**
 * 横向溢出守门：**页面本体永远不横向滚动。**
 *
 * 这条规则本仓早就写下了，但违反它的时候肉眼完全看不出来——
 * 研究任务页曾被撑到 4258px（视口 1425px），左边三分之一一切正常，
 * 只有滚动条变长了一点。是量出来才发现的。
 *
 * 这里不启动浏览器，而是守住产生这类问题的**根因模式**：
 * flex / grid 的子项默认 min-width: auto，一个不换行的长串会把整条轨道撑开。
 * 凡是"里面有 white-space: nowrap"的容器，自己必须有 min-width: 0。
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../styles.css"), "utf8");

/** 抽出一条规则的声明块。选择器要完全匹配，避免 .a 匹到 .ab。 */
function rule(selector: string): string | null {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(^|\\n)\\s*${escaped}\\s*\\{([^}]*)\\}`));
  return match ? match[2] : null;
}

test("带 nowrap 子元素的 flex 容器必须自己能收缩", () => {
  // task-review 是实际出过事的那一处：summary 里的 em 是 nowrap 单行省略号，
  // 而 summary 自己缩不下去，整页被撑到 4258px。
  const summary = rule(".task-review > summary");
  assert.ok(summary, "找不到 .task-review > summary 这条规则");
  assert.match(summary!, /min-width:\s*0/,
    "summary 里有 nowrap 的子元素，它自己必须 min-width: 0，否则整页横向溢出");
});

test("那个 em 的单行省略号三件套要齐全", () => {
  // 少任何一件，要么撑开、要么文字直接截断没有省略号
  const em = rule(".task-review > summary em");
  assert.ok(em, "找不到 .task-review > summary em");
  for (const need of [/min-width:\s*0/, /overflow:\s*hidden/, /text-overflow:\s*ellipsis/, /white-space:\s*nowrap/]) {
    assert.match(em!, need, `单行省略号缺一不可：${need}`);
  }
});
