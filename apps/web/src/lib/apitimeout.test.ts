/**
 * 请求要有超时上限——**没有上限的转圈比报错更难受**。
 *
 * 原来 `apiFetch` 直接 `fetch(...)`，没有 signal：移动网络切换、后端卡在
 * 一次外部数据源上、反代断了但没关连接，这几种情况下按钮会永远停在
 * 「正在…」，用户唯一能做的是刷新整页——而刷新会把没保存的输入一起丢掉。
 *
 * 这里测的是源码结构（有没有挂上超时、慢接口有没有单独放宽），
 * 因为真正要防的是"有人加了一条新的 fetch 却忘了走 apiFetch"这类回归，
 * 而不是某一次请求的行为。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const api = readFileSync(join(import.meta.dirname, "..", "api.ts"), "utf8");

test("apiFetch 给每个请求挂了超时", () => {
  assert.match(api, /AbortSignal\.timeout\(/,
    "apiFetch 里要有 AbortSignal.timeout —— 没有它，一次卡住的请求会让按钮永远转圈");
  assert.match(api, /signal,\s*\}\);/s,
    "signal 必须真的传进 fetch 的选项里，光算出来不用等于没有");
});

test("模型调用另有一档更长的超时", () => {
  // 深度报告、反方复核本来就要一两分钟。用同一个 20 秒会把正常的调用掐掉，
  // 而那种失败最贵：积分已经冻结、模型已经在跑，用户看到的却是「超时」。
  //
  // 分档的逻辑搬到了 ./timeouts，那里能直接调真函数（api.ts 带 Vite 的
  // import.meta.env，node --test 里 import 不进来，所以这份只能读源码文本）。
  // 档位本身在 ./timeouts.test.ts 里逐条验，这里只确认 api.ts 真的用了它。
  assert.match(api, /from "\.\/lib\/timeouts"/,
    "api.ts 要从 lib/timeouts 拿分档逻辑");
  assert.match(api, /timeoutFor\(path,\s*options\?\.method/,
    "算超时时要把请求方法一起传进去 —— 同一个路径 GET 快、POST 才调模型");
});

test("超时要说成人话，不是抛一个 TimeoutError", () => {
  assert.match(api, /TimeoutError/, "要认出超时这一种取消");
  assert.match(api, /请求超时/, "给用户的文案要说明白是超时，并且能重试");
});

test("options 展开在前，headers 与 signal 不会被顶掉", () => {
  // 原来 `...options` 排在 headers 后面：调用方一旦自带 headers，
  // 合并好的 Content-Type 会被整个顶掉，而 TypeScript 不会报错。
  const call = api.slice(api.indexOf("response = await fetch(apiUrl(path)"), api.indexOf("} catch (error)"));
  const spread = call.indexOf("...options,");
  const headers = call.indexOf("headers:");
  const signal = call.indexOf("signal,");
  assert.ok(spread >= 0 && spread < headers && headers < signal,
    "顺序必须是 ...options → headers → signal");
});
