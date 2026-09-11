/**
 * 兜底的错误文案。**它被用在 126 个地方，所以每个字都得对这 126 处都成立。**
 *
 * 2026-08-19 巡检把请求掐断，点「同步实时行情」、切收件箱筛选，
 * 弹出来的都是同一句：
 *
 *     "保存失败，请检查 API 是否正在运行。"
 *
 * 两处都不是"保存"。而后半句是对开发者说的 —— 用线上站点的人做不到
 * 「检查 API 是否正在运行」，也不该被要求去想这件事。
 * Documents.tsx 里还有一句同病的「请检查后端是否在跑」。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";
import { errorMessage } from "./errormessage.ts";

test("后端给了文案就用后端的", () => {
  assert.equal(errorMessage({ message: "成交价要大于 0。" }), "成交价要大于 0。");
  assert.equal(errorMessage(new Error("请求超时（超过 20 秒没有响应），稍后再试。")),
    "请求超时（超过 20 秒没有响应），稍后再试。");
});

test("拿不到响应时说连不上，并给一件用户能做的事", () => {
  const said = errorMessage(undefined);
  assert.match(said, /连不上/, "没说清是连不上服务器");
  assert.match(said, /重试|再试/, "没告诉用户下一步能做什么");
});

test("不许声称是哪一步失败了", () => {
  // 同一句话要盖住同步、筛选、删除、生成…… 说「保存失败」在绝大多数场合都是错的。
  for (const claim of ["保存", "读取", "上传", "删除"]) {
    assert.doesNotMatch(errorMessage(null), new RegExp(claim),
      `兜底文案里出现了「${claim}」—— 它对另外一百多处不成立`);
  }
});

test("不许把开发者的活派给用户", () => {
  const said = errorMessage(null);
  for (const dev of ["API", "后端", "服务是否", "是否正在运行", "是否在跑"]) {
    assert.ok(!said.includes(dev), `兜底文案里出现了「${dev}」—— 用线上站点的人做不到这件事`);
  }
});

test("两个文件共用同一句，不许各写各的", () => {
  const here = join(import.meta.dirname, "..");
  for (const f of ["App.tsx", "components/Documents.tsx"]) {
    const src = readFileSync(join(here, f), "utf8");
    assert.match(src, /from "\.{1,2}\/lib\/errormessage"/, `${f} 没有共用这一句`);
    assert.doesNotMatch(src, /function errorMessage\(/, `${f} 又自己写了一份 —— 两份会立刻分叉`);
  }
});
