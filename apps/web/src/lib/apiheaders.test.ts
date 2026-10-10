/** 调用方不许自己传 content-type。
 *
 * `apiFetch` 已经设了 `Content-Type: application/json`。调用方再传一个小写的
 * `content-type`，在 JS 对象字面量里是**两个不同的键**——两个都会进 Headers，
 * 合并成 `application/json, application/json`，于是 Starlette 认不出这是 JSON，
 * 把整个 body 原样当字符串交给 pydantic，回一个 `model_attributes_type` 的 422。
 *
 * **四处都是静默失败**：请求发出去了、后端回了 422、页面上什么都没变。
 * 实测栽过的：
 *   saveSettings          偏好设置存不进去
 *   updatePortfolio       改不了组合名字和目标
 *   createTradesBatch     交割单读完之后「确认入账」那一步
 *   purgeCompanyTrades    按公司清空流水
 *
 * 这条判据是 2026-09-23 用户问「为啥持仓那个，还是没办法做删除」才挖出来的，
 * 而前三处在那之前已经坏了不知道多久 —— 没有任何测试会红。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const API = join(here, "..", "api.ts");

test("apiFetch 的调用方不许自己传 content-type", () => {
  const source = readFileSync(API, "utf8");
  const offenders: string[] = [];
  source.split("\n").forEach((line, index) => {
    if (!/content-type/i.test(line)) return;
    // apiFetch 自己设的那一行是唯一合法的。
    if (line.includes('Accept: "application/json"')) return;
    // 注释里解释这个坑的不算。
    if (/^\s*(\/\/|\*|\/\*)/.test(line)) return;
    offenders.push(`api.ts:${index + 1}: ${line.trim()}`);
  });
  assert.deepEqual(offenders, [],
    "这些地方自己传了 content-type，会和 apiFetch 设的那个撞成两份，"
    + "请求变成非 JSON、后端 422、页面上毫无反应：\n" + offenders.join("\n"));
});

test("apiFetch 自己那一行还在", () => {
  // **分母会动就单独钉一条。** 上面那条判据的前提是 apiFetch 确实设了头；
  // 哪天它被删掉，上面那条照样全绿，而所有 POST 都会变成非 JSON。
  const source = readFileSync(API, "utf8");
  assert.match(source, /headers: \{ "Content-Type": "application\/json", Accept: "application\/json", \.\.\.options\?\.headers \}/);
});
