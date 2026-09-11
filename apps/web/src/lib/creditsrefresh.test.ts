/**
 * **花过钱的调用要通知顶栏刷新余额。**
 *
 * 主站定了这个约定（xiamimate-tools-frontend/lib/api.ts）：AI 调用成功后派一个
 * `xm-credits-changed`，页眉的积分胶囊听到就重新拉余额。
 *
 * 而 stock-lab 是独立前端，**从来没发过这个事件** —— 扣完分之后顶栏还显示旧数，
 * 要用户自己去点一下才刷新。使用者原话：「消费积分没有很快响应，
 * 还需要用户去点击才能刷新看到最新积分」。
 *
 * 这条守卫扫源码，不跑浏览器：约定的名字写错一个字母，页眉就永远收不到，
 * 而**没有任何地方会报错** —— 表现只是"余额刷得慢"，跟网络慢分不出来。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const API = readFileSync(new URL("../api.ts", import.meta.url), "utf8");

test("扣过分之后要派 xm-credits-changed", () => {
  assert.ok(API.includes('new CustomEvent("xm-credits-changed")'),
    "stock-lab 没有派这个事件 —— 顶栏的积分胶囊不会刷新，得用户自己去点");
});

test("事件名跟主站一字不差", () => {
  // 主站发的是 `xm-credits-changed`。写成 xm_credits_changed 或 credits-changed
  // 都不会报错，只是页眉永远收不到 —— 而那跟"网络慢"分不出来。
  const names = [...API.matchAll(/new CustomEvent\("([^"]+)"\)/g)].map((m) => m[1]);
  assert.deepEqual(names, ["xm-credits-changed"],
    `派了别的事件名：${names.join("、")} —— 主站只听 xm-credits-changed`);
});

test("只在会花钱的路径上派，而且只在成功时派", () => {
  const at = API.indexOf('new CustomEvent("xm-credits-changed")');
  const before = API.slice(Math.max(0, at - 400), at);
  assert.ok(before.includes("isModelCall("),
    "对所有请求都派的话，读一次列表也会让顶栏跳一下 —— 那是噪声");
  // **必须跟超时用同一个判定。** 原来这里和 timeoutFor 各写各的
  // `SLOW_PATHS.some(...)`，加一条模型接口时只改一处，
  // 表现出来就是「跑完了，但顶栏的积分还是旧数」。
  assert.ok(before.includes("options?.method"),
    "判定要带上请求方法，否则 POST 才花钱的那几条会被漏掉");
  // 必须在 `if (!response.ok)` 那一段之后：失败没扣钱，派了等于让人白看一次跳动
  assert.ok(API.indexOf("if (!response.ok)") < at,
    "派在错误分支之前了 —— 失败也会通知刷新，而那时候余额根本没变");
});
