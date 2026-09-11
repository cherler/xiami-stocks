import assert from "node:assert/strict";
import { test } from "node:test";

import { splitClauses, splitOutsideBrackets, thesisRest } from "./thesisText.ts";

// 取自库里真实的一条投资逻辑（中国平安），就是它在页面上被切碎的。
const CLAIM = "赌的是保险综合金融组合的低估值与高现金流开始兑现到股东回报；"
  + "估值端市净率已破净，市盈率TTM处于近5年偏低分位（市盈率TTM 7.37 倍，处于近 5 年 12.7% 分位；"
  + "市净率 0.96 倍，处于近 5 年 35.2% 分位，2026-08-05）；"
  + "经营现金流远超净利润，盈利的现金含量高（现金含量 394.02%，上一年度同口径 416.06%，2026-03-31 一季报）";

const COUNTER = "1）总资产收益率、2026 年中报口径低于 0.5%（一季度为 0.23%，同比已从 1.14% 明显回落）——资产端扩张快于利润生成 "
  + "2）应收周转天数、中报口径超过 22 天（一季度已升至 18.9 天，上年同期 15.2 天）——账期被动拉长以维持收入 "
  + "3）现金含量、中报口径连续两期低于 150%（一季度 394.02%，上年同期 416.06%）——经营现金流不再覆盖净利润 "
  + "4）公告类别（分红／股权变动）、若后续出现「不实施分红」类公告——承诺被打破";

test("括号里的分号不切开", () => {
  const parts = thesisRest(CLAIM);

  assert.equal(parts.length, 2, `切成了 ${parts.length} 段：${JSON.stringify(parts)}`);
  // 每一段的括号都要配平——不配平就是从括号中间断开了
  for (const part of parts) {
    const open = [...part].filter((c) => c === "（").length;
    const close = [...part].filter((c) => c === "）").length;
    assert.equal(open, close, `括号对不上：${part}`);
  }
});

test("小数点不是列表标记", () => {
  const parts = splitClauses(COUNTER);

  assert.equal(parts.length, 4, `切成了 ${parts.length} 条：${JSON.stringify(parts.slice(0, 8))}`);
  // 上一版会把「394.02%」切成「3」「9」「4.02%」，页面上是一串孤零零的数字
  for (const part of parts) {
    assert.ok(part.length > 10, `切出了一个碎片：「${part}」`);
  }
  assert.ok(parts[1].includes("18.9 天"), "「18.9」被切成了「1」和「8.9」");
  assert.ok(parts[2].includes("394.02%"), "「394.02%」被切碎了");
});

test("编号要出现在条目开头", () => {
  const parts = splitClauses(COUNTER);
  parts.forEach((part, index) => {
    assert.ok(part.startsWith(`${index + 1}）`), `第 ${index + 1} 条开头不对：${part.slice(0, 20)}`);
  });
});

test("没有编号就整段返回，不硬切", () => {
  const plain = "这是一段没有任何编号的反证条件，写了 3 个要点但没编号，不该被拆开。";

  assert.deepEqual(splitClauses(plain), [plain]);
});

test("空输入返回空数组", () => {
  assert.deepEqual(splitClauses(""), []);
  assert.deepEqual(splitClauses("   "), []);
});

test("嵌套括号也不切", () => {
  const text = "第一段；第二段（里面有（嵌套）和分号；还有内容）；第三段";

  assert.deepEqual(splitOutsideBrackets(text, "；"),
    ["第一段", "第二段（里面有（嵌套）和分号；还有内容）", "第三段"]);
});

test("百分号与年份不会被当成编号", () => {
  const text = "现金含量 394.02%，上年同期 416.06%，2026-03-31 一季报";

  assert.deepEqual(splitClauses(text), [text]);
});
