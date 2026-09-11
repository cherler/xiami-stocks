/**
 * 只有日期的东西不许印出时分。
 *
 * ## 这条是看截图看出来的
 *
 * 证据档案里四条并排，每一条都写着 `8月18日 00:00`。
 * 追下去：公告和大事只有 `event_date`（一个日子），后端为了凑成时间戳补了
 * `T00:00:00`（repository.py:3376），前端再无条件把时分打出来。
 *
 * 那个 `00:00` 是**假精度** —— 它看起来像"这件事发生在零点"，
 * 而真相是"我们只知道是哪一天"。这跟本仓反复守的那条是同一件事：
 * **看起来能用的数字比没有数字糟**，因为读的人不会去怀疑它。
 *
 * 顺带它还把一列本来能区分先后的信息变成了噪音：四条都是 00:00，等于没排序。
 *
 * ## 边界在哪
 *
 * 真的发生在零点零分的事（少见但存在）会被一起当成"只有日期"。
 * 这个取舍是有意的：把一个真零点显示成日期，代价是丢掉"零点"这一个信息；
 * 把一堆补出来的零点显示成时刻，代价是给每一条都编一个发生时间。
 * 后者贵得多。而 `00:05` 这种照常显示 —— 判据是整点整分，不是"零点前后"。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { formatDateTime, looksDateOnly } from "./datetime.ts";

test("补出来的零点只显示日期，真实时刻照常显示", () => {
  for (const only of ["2026-08-18T00:00:00", "2026-08-18T00:00", "2026-08-18"]) {
    assert.equal(formatDateTime(only), "8月18日", `${only} 不该印出 00:00`);
  }
  assert.equal(formatDateTime("2026-08-18T11:36:00"), "8月18日 11:36");
  // **零点零五分是真的时刻，要显示。** 判据是整点整分，不是"零点前后"
  assert.equal(formatDateTime("2026-08-18T00:05:00"), "8月18日 00:05");
});

test("App.tsx 用的就是这个函数，不是自己抄了一份", () => {
  // 第一版这条守卫是**假的**：它只查 App.tsx 里有没有 `const midnight =` 和
  // `T00:00` 这两段文字，于是把判据改成 `false && /T00:00/` 照样绿 ——
  // 破坏验证时当场发现。真正的修法是把函数搬进 lib、两边用同一个，
  // 测试直接调它，行为变了就会红。
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.ok(app.includes('from "./lib/datetime"'), "App.tsx 没有引这个模块");
  assert.ok(!app.includes("function formatDateTime"),
    "App.tsx 里又自己写了一份 formatDateTime —— 两份会漂，而漂了不会响");
  assert.equal(looksDateOnly("2026-08-18T00:00:00"), true);
  assert.equal(looksDateOnly("2026-08-18T00:05:00"), false);
});

test("样本铺不满窗口时，标题不许说「近 N 年分位」", () => {
  // ── 这一条守什么 ──────────────────────────────────────────────
  // 实测（寒武纪）：它 2025-04 才转正、之前没有 PE，序列只有 1.33 年。
  // 而页面给的是「近 3 年分位 5.6%」和「近 5 年分位 5.6%」—— 同一个数，
  // 因为背后是同一批 16 个月的样本。
  //
  // 读的人会理解成"比过去五年里 94% 的时间都便宜"，**而过去五年根本没有数据**。
  // 这不是少一句提示，是**标题在替这个数字说一件没发生过的事**。
  //
  // 后端已经把真实跨度交出来了（covered_years / coverage_note），
  // 所以这里守的是页面有没有用它：铺不满就把标题换成真实跨度。
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const at = app.indexOf('className="valuation-window-head"');
  assert.ok(at > 0, "找不到分位那一块 —— 这个守卫自己瞎了");
  const head = app.slice(at - 900, at + 500);
  assert.ok(head.includes("window.coverage_note"),
    "分位标题没有看 coverage_note —— 样本只有 1.33 年时它仍然会说「近 5 年分位」");
  assert.ok(head.includes("covered_years"),
    "标题里要给出真实跨度，否则读的人不知道这个分位回答的不是他问的那个问题");

  // 两段几乎相同的红字（只差「不足 3 年」「不足 5 年」）不许再各印一遍
  const block = app.slice(at, at + 2600);
  assert.ok(!/valuation-reason--warn/.test(block),
    "每个窗口下面又各印了一遍那段警告 —— 内容几乎相同，第二段不带任何新信息");
});
