/**
 * 接口地址守门：**每一次 fetch 都要经过 `apiUrl()`。**
 *
 * 这个应用挂在子路径下（线上 `/stocks/`），接口前缀是 `/stocks-api`——
 * 因为 `/api/*` 已经被主站的 AI 闸口占用。所以裸写 `fetch("/api/v1/...")`
 * 在本机 `npm run dev` 下能跑通（Vite 代理转 8108），一发到线上就 404，
 * 而且打到的是**别人的服务**，不是自己的后端。
 *
 * 已经栽过两次：
 * - `deleteScreenStrategy` 裸写路径 → 用户点删除，看到「请求失败（404）」；
 * - `deleteResearchTask` 把 `apiUrl` 这个**函数本身**插进模板串，
 *   URL 变成 `function apiUrl(path){...}/api/v1/tasks/3`。
 *
 * 两处都是「本机开发跑得通」的错——只有部署形态才暴露，所以要靠测试挡。
 */

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const SRC = join(import.meta.dirname, "..");

function sourceFiles(): string[] {
  return readdirSync(SRC, { recursive: true, encoding: "utf8" })
    .filter((name) => /\.tsx?$/.test(name) && !name.endsWith(".test.ts"))
    .map((name) => join(SRC, name));
}

test("所有 fetch 都经过 apiUrl()，没有裸写的接口路径", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const text = readFileSync(file, "utf8");
    for (const line of text.split("\n")) {
      // 只看真正发请求的 fetch(...)，跳过 apiFetch / prefetch 这类名字里带 fetch 的
      if (!/(^|[^A-Za-z])fetch\(/.test(line)) continue;
      if (/fetch\(apiUrl\(/.test(line)) continue;
      offenders.push(`${file.slice(SRC.length + 1)}: ${line.trim()}`);
    }
  }
  assert.deepEqual(offenders, [],
    "这些 fetch 没走 apiUrl()：子路径部署下会打到 /api/*——那是主站的闸口，不是本应用的后端。\n" +
    "改成 apiFetch(...)，或至少 fetch(apiUrl(path))。\n" +
    offenders.join("\n"));
});

test("下载链接也要经过 apiUrl()——fetch 不是唯一发请求的东西", () => {
  // **上面那条测试挡不住 `<a href>`。** 它只看 fetch(，而下载是浏览器
  // 直接跟着 href 走的，一行 JS 都不执行。
  //
  // 于是三个下载入口在线上一直是坏的（2026-08-13 实测 `/api/v1/companies/export`
  // 在主站入口下返回 404，同一接口走 `/stocks-api/api/v1/...` 返回 200）：
  // 导出研究池、导出 JSON、**以及备份下载**。最后那个尤其不该坏——
  // 它正是"出事了怎么捞回来"的那条路，而它平时没人点，坏了也没人知道。
  //
  // 审查报告只点了前两处，第三处是补测这条时才发现的。这就是为什么
  // 判据要写成「所有 href」，而不是把已知的那几个地址列进白名单。
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const text = readFileSync(file, "utf8");
    for (const line of text.split("\n")) {
      // href="/api/..." 与 href={`/api/...`} 两种写法都要拦
      if (!/href=(["']\/api\/|\{`\/api\/)/.test(line)) continue;
      offenders.push(`${file.slice(SRC.length + 1)}: ${line.trim()}`);
    }
  }
  assert.deepEqual(offenders, [],
    "这些下载链接裸写了 /api：子路径部署下点了会得到主站的 404 页，而不是文件。\n" +
    "改成 href={apiUrl(\"/api/v1/...\")}。\n" +
    offenders.join("\n"));
});

test("apiUrl 只能被调用，不能被插进模板串", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const text = readFileSync(file, "utf8");
    // ${apiUrl} 会把函数源码拼进 URL，且 TypeScript 不报错
    if (/\$\{apiUrl\}/.test(text)) offenders.push(file.slice(SRC.length + 1));
  }
  assert.deepEqual(offenders, [],
    "`${apiUrl}` 拼的是函数源码，不是地址。要写 `apiUrl(path)`。");
});

test("apiFetch 认得 204：没有 body 的成功不能当成失败", () => {
  const api = readFileSync(join(SRC, "api.ts"), "utf8");
  const guard = api.indexOf("response.status === 204");
  const parse = api.indexOf("return response.json() as Promise<T>");
  assert.ok(guard > 0,
    "apiFetch 里要有 204 分支——删除类接口返回 204 且没有 body，\n" +
    "直接 .json() 会抛异常：后端删干净了，用户看到的却是「删不掉」。");
  assert.ok(guard < parse, "204 的判断必须在 response.json() 之前");
});
