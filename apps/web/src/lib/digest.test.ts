/**
 * 读文档结果里那张表：**行列对齐、数字靠右、两边字段名一致**。
 *
 * ## 第三条为什么要用测试守
 *
 * 这张表的数据链是：提示词让模型输出 `tables.columns` / `tables.rows` → 存成一段
 * JSON → 前端读 `item.tables`。**中间没有任何一层会检查字段名对不对。**
 * 名字写错的表现是"表格不显示"，而那跟"这份文件里本来就没有表"长得一模一样 ——
 * 这个仓里已经栽过两次：`meetings`/`fundraising` 从来没传进去，单元测试全绿，
 * 功能在线上是死的。所以这里直接去读提示词里那份 JSON 样例，逐个字段对。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { numeric, tableGrid } from "./digest.ts";

test("行比表头多一格或少一格，都不许丢格子", () => {
  const grid = tableGrid({
    columns: ["科目（百万元）", "2024E", "2025E"],
    // 第一行少一格，第二行多一格 —— 模型两种都犯过
    rows: [["营业收入", "1536"], ["归母净利润", "-70", "182", "237"]],
  });
  assert.equal(grid.columns.length, 4, "多出来的那一格要给表头补一个空标题");
  assert.deepEqual(grid.columns, ["科目（百万元）", "2024E", "2025E", ""]);
  assert.deepEqual(grid.rows[0], ["营业收入", "1536", "", ""], "少的补空");
  assert.deepEqual(grid.rows[1], ["归母净利润", "-70", "182", "237"],
    "多的一格不许截掉——被截掉的正好可能是最要紧的那个数，而截完看起来完全正常");
});

test("空表、缺字段都不炸", () => {
  assert.deepEqual(tableGrid({}), { columns: [], rows: [] });
  assert.deepEqual(tableGrid({ columns: ["科目"], rows: [] }), { columns: ["科目"], rows: [] });
});

test("以数字打头的格子算数，靠右；科目名靠左", () => {
  for (const cell of ["1536", "-70", "–848", "0.44", "69.16%", "1,118", "29X", "922.78 亿"]) {
    assert.equal(numeric(cell), true, `${cell} 该靠右`);
  }
  for (const cell of ["营业收入", "归母净利润", "", "—", "不适用"]) {
    assert.equal(numeric(cell), false, `${cell} 该靠左`);
  }
});

test("提示词里那份 JSON 样例，字段名跟前端读的一致", () => {
  const prompt = readFileSync(new URL("../../../api/stock_decision/documents.py", import.meta.url),
    "utf8");
  const digest = prompt.slice(prompt.indexOf("DIGEST_SYSTEM_PROMPT"),
    prompt.indexOf("def build_digest_prompt"));
  assert.ok(digest.length > 200, "没找到 DIGEST_SYSTEM_PROMPT，这个测试自己瞎了");
  // 前端 DigestBoard / Card / Table 读的就是这几个键
  for (const key of ["watch", "point", "items", "title", "verdict", "found",
                     "figures", "label", "value", "note",
                     "tables", "columns", "rows", "pages"]) {
    assert.ok(digest.includes(`"${key}"`), `提示词里没有 "${key}" —— 前端读得到空`);
  }
});
