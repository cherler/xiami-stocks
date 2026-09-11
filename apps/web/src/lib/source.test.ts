/**
 * 出处记号守门：**「模型推断」永远不给可点的链接。**
 *
 * 这个产品跟所有炒股软件的区别只有一条：每个数都能点回原文核对。
 * 而「年报原文」和「模型推断」在页面上必须一眼分得开——那正是最该守住的区别。
 *
 * 原来它只靠一段文字说明（「关系来自模型的世界知识，可能过期也可能记错」）。
 * **一段说明挡不住任何人把推断当事实**；一个没有链接的记号挡得住。
 *
 * 所以这条测试盯的是：有人给 Source 加功能时，不会顺手让「模型推断」
 * 也变成可点的——那一刻这个记号就失去了全部意义，而页面上看不出任何变化。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const SOURCE = readFileSync(
  join(import.meta.dirname, "..", "components", "Source.tsx"), "utf8");

test("模型推断那一档不给可点的链接", () => {
  // 走到 <a> 那一支的条件里必须排除「模型推断」
  const linked = /if \(kind !== "模型推断" && href\)/.test(SOURCE);
  assert.ok(linked,
    "生成 <a> 的分支必须显式排除「模型推断」——\n" +
    "让它变成可点的那一刻，这个记号就失去了全部意义，而页面上看不出变化。");
});

test("四种来源都在，且各自的说明不一样", () => {
  for (const kind of ["年报", "公告", "底座", "模型推断"]) {
    assert.ok(SOURCE.includes(`${kind}:`), `少了来源类型：${kind}`);
  }
  // 「模型推断」的说明里必须写明它没有出处
  assert.match(SOURCE, /模型推断: "[^"]*没有可核对的出处/,
    "「模型推断」的提示里必须写明它没有出处，而不是含糊带过");
});
