import { test } from "node:test";
import assert from "node:assert/strict";

import { nextCursor } from "./listcursor.ts";

test("没选中时往下一格落在第一条", () => {
  // 第一版是 `+ count + 1`，这里会返回 1——**第一次按下就跳过了第一条**。
  assert.equal(nextCursor(-1, 1, 7), 0);
});

test("没选中时往上一格落在最后一条", () => {
  assert.equal(nextCursor(-1, -1, 7), 6);
});

test("一次只走一格", () => {
  assert.equal(nextCursor(0, 1, 7), 1);
  assert.equal(nextCursor(1, 1, 7), 2);
  assert.equal(nextCursor(2, -1, 7), 1);
});

test("到头了绕回去", () => {
  assert.equal(nextCursor(6, 1, 7), 0);
  assert.equal(nextCursor(0, -1, 7), 6);
});

test("空列表不选中任何一条", () => {
  // 不加这条会算出 NaN，高亮跟着变成 undefined ——按回车就什么都不会发生。
  assert.equal(nextCursor(-1, 1, 0), -1);
});
