/**
 * 被网关挡下和被后端拒绝，是两回事。
 *
 * 2026-08-19 巡检：把 `<img src=x onerror=alert(1)>` 写进判断的正文，
 * 网关回 **403 + 一整页 HTML**（不是 JSON）。拆开写（`<img src=x>` 和
 * `onerror=` 各自一段）就 200 —— 挡的是完整的攻击特征，挡得对。
 *
 * 但用户看到的是「**请求失败（403）**」：一个裸状态码，
 * 读起来像"没权限"，而真实原因是"你写的内容里有被当成攻击特征的片段"，
 * 并且**重试一万次都一样**，只有改写内容才行。
 *
 * 这跟已有的 unreachable()（5xx + 非 JSON = 后端没起来）是同一个形状的另一半。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const API = readFileSync(join(import.meta.dirname, "..", "api.ts"), "utf8");

test("4xx 且不是 JSON 时，要说是网关挡的", () => {
  assert.match(API, /payload === null && response\.status >= 400/,
    "没有识别「拿不到 JSON 的 4xx」这一类 —— 它会掉进裸状态码那条路");
  assert.match(API, /function blockedByGateway\(/);
});

test("那句话要说清为什么、以及该做什么", () => {
  const at = API.indexOf("function blockedByGateway(");
  const body = API.slice(at, API.indexOf("\n}", at));
  assert.match(body, /网关/, "没说是被谁挡的");
  assert.match(body, /没有到后端/, "没说清请求根本没走到后端 —— 否则人会去怀疑数据坏了");
  assert.match(body, /script|onerror/, "没给出具体是什么片段，人无从下手");
  assert.match(body, /改写/, "没告诉用户该做什么 —— 这一类重试没有意义");
});

test("5xx 那一支还留着，两种情况不能合并", () => {
  // 一个是"它没起来、重试也一样"，一个是"你写的内容过不去"。
  // 合并成一句的话，本地开发时又会去翻后端日志 —— 那里什么都没有。
  // **带上右括号。** 第一版写的是 /response\.status >= 500/，
  // 而 `>= 5000` 里也含这个子串 —— 把 500 改成 5000 的突变照样绿。
  assert.match(API, /payload === null && response\.status >= 500\)/,
    "5xx 那一支不见了（或者阈值被改过）");
  assert.match(API, /function unreachable\(/);
  // 顺序不能反：5xx 要先判，否则会被 >= 400 那一支吞掉。
  const at500 = API.indexOf("response.status >= 500)");
  const at400 = API.indexOf("response.status >= 400)");
  assert.notEqual(at500, -1, "找不到 5xx 分支");
  assert.notEqual(at400, -1, "找不到 4xx 分支");
  assert.ok(at500 < at400, "5xx 的判断排在 4xx 后面了 —— 500 会被当成网关拦截");
});
