/**
 * 超时档位与「这次会不会花钱」。**调的是真的那两个函数**，不是照规则抄一份。
 *
 * 默认 20 秒是按"本地一条 SQL + 一次外部行情"给的；模型调用几十秒起步。
 * 2026-08-18 线上撞到：「自动整理收件箱」（POST /api/v1/inbox/tidy）
 * 不在任何一张表里，一次要跑五批模型分级 —— 点下去必然
 * 「请求超时（超过 20 秒没有响应）」，这个按钮从上线起就没成功过。
 * 顺着查出同一类的还有三条。
 *
 * 后端那一侧由 apps/api/tests/test_model_routes_are_declared_slow.py 从**真实
 * 调用图**里找「模型跑在请求里」的路由，新增一条会红，逼人回来改这张表。
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { SLOW_TIMEOUT_MS, TIMEOUT_MS, isModelCall, timeoutFor } from "./timeouts.ts";

test("模型跑在请求里的接口，给的是长超时", () => {
  // 这四条是 2026-08-18 从后端调用图里查出来的，「自动整理收件箱」是报错那条。
  assert.equal(timeoutFor("/api/v1/inbox/tidy?use_ai=true", "POST"), SLOW_TIMEOUT_MS);
  assert.equal(timeoutFor("/api/v1/counter-hits/check", "POST"), SLOW_TIMEOUT_MS);
  assert.equal(timeoutFor("/api/v1/value-candidates?strategy=x&width=3", "POST"), SLOW_TIMEOUT_MS);
  assert.equal(timeoutFor("/api/v1/companies/8/evidence-direction", "POST"), SLOW_TIMEOUT_MS);
});

test("原来那张子串表照常管用", () => {
  assert.equal(timeoutFor("/api/v1/companies/8/deep-report", "POST"), SLOW_TIMEOUT_MS);
  assert.equal(timeoutFor("/api/v1/documents/3/digest", "POST"), SLOW_TIMEOUT_MS);
});

test("同一个路径的 GET 是读已经算好的结果，不跟着变慢", () => {
  // 请求真挂住时，快的那半边要在 20 秒报错，而不是让人干等四分钟。
  assert.equal(timeoutFor("/api/v1/companies/8/evidence-direction"), TIMEOUT_MS);
  assert.equal(timeoutFor("/api/v1/value-candidates/review/status?strategy=x"), TIMEOUT_MS);
  assert.equal(timeoutFor("/api/v1/counter-hits"), TIMEOUT_MS);
});

test("邻近路径不会被顺手拖慢", () => {
  // 存一份筛选结果、确认一条命中，都是本地一条 SQL。
  assert.equal(timeoutFor("/api/v1/value-candidates/saved", "POST"), TIMEOUT_MS);
  assert.equal(timeoutFor("/api/v1/counter-hits/12/acknowledge", "POST"), TIMEOUT_MS);
  assert.equal(timeoutFor("/api/v1/companies"), TIMEOUT_MS);
});

test("会花钱的判定跟超时是同一个，顶栏余额不会停在旧数", () => {
  // 这两处原来各写各的 SLOW_PATHS.some(...)，加路径时只改一处的话，
  // 表现出来是「整理完了，但顶栏的积分还是旧数」。
  assert.equal(isModelCall("/api/v1/inbox/tidy?use_ai=true", "POST"), true);
  assert.equal(isModelCall("/api/v1/companies/8/evidence-direction", "POST"), true);
  // 读操作不花钱，别让顶栏白闪一下。
  assert.equal(isModelCall("/api/v1/companies/8/evidence-direction"), false);
  assert.equal(isModelCall("/api/v1/inbox?days=90"), false);
});

test("id 归一化只吃路径段，不吃 query 里的数字", () => {
  assert.equal(timeoutFor("/api/v1/companies/123/evidence-direction", "POST"), SLOW_TIMEOUT_MS);
  assert.equal(timeoutFor("/api/v1/inbox/tidy?use_ai=true&limit=2000", "POST"), SLOW_TIMEOUT_MS);
});

test("同步行情不靠放宽超时 —— 它是后台任务", () => {
  // 这里一度有第三档 90 秒，为「同步实时行情」加的。**线上复验时它又超了**：
  // 那活要跑几分钟（底座是全市场 5544 只）。继续加大只是把"静默失败"
  // 换成"干等四分钟"，所以那个接口改成了后台任务 —— POST 起完就返回。
  assert.equal(timeoutFor("/api/v1/market/refresh", "POST"), TIMEOUT_MS);
  // 也不花积分，别让顶栏白闪一下余额。
  assert.equal(isModelCall("/api/v1/market/refresh", "POST"), false);
});

test("公司那几条同步是快的，别跟着放宽", () => {
  // 实测 0.8～8.6 秒。放宽了的话，它们真挂住时也要等一分半。
  for (const p of ["profile", "valuation", "financials", "market-history"]) {
    assert.equal(timeoutFor(`/api/v1/companies/8/${p}/refresh`, "POST"), TIMEOUT_MS, p);
  }
});
