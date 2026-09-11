/**
 * 确认框：**不许再出现 window.confirm，也不许漏掉 await。**
 *
 * 这两条都是"编译能过、跑起来才错"的类型：
 *
 * - `window.confirm` 阻塞主线程、手机上带出主站域名，而且在自动化测试里
 *   会被自动 dismiss —— 也就是说漏网的那一处，冒烟脚本会"静默取消"而不报错。
 * - `confirmAction()` 返回 Promise。忘了 await 的话 `if (!confirmAction(...))`
 *   里那个 Promise 恒为真值，条件恒为假，**动作会直接执行**——
 *   删除照删、积分照扣，而且一句报错都没有。TypeScript 不会拦这个。
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

test("没有任何地方再用 window.confirm", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    const text = readFileSync(file, "utf8");
    // lib/confirm.tsx 里那一处是 Host 没挂时的兜底，允许
    if (file.endsWith("lib/confirm.tsx")) continue;
    text.split("\n").forEach((line, index) => {
      // 注释里提到它是可以的（好几处注释在讲"为什么不用它"）
      if (/^\s*(\/\/|\*|\/\*)/.test(line)) return;
      if (line.includes("window.confirm")) offenders.push(`${file.slice(SRC.length + 1)}:${index + 1}`);
    });
  }
  assert.deepEqual(offenders, [],
    "这些地方还在用原生确认框，改成 confirmAction({ title, detail, danger })：\n" + offenders.join("\n"));
});

test("confirmAction / confirmSpend 一定被 await 了", () => {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    if (file.endsWith("lib/confirm.tsx") || file.endsWith("lib/credits.ts")) continue;
    const text = readFileSync(file, "utf8");
    text.split("\n").forEach((line, index) => {
      for (const name of ["confirmAction(", "confirmSpend("]) {
        const at = line.indexOf(name);
        if (at < 0) continue;
        const before = line.slice(0, at);
        // 允许 `await x(`、`= x(` 这类把 Promise 接住的写法；
        // 拦的是 `if (!x(` / `if (x(` 这种直接当布尔用的
        if (/await\s*$/.test(before) || /[=:]\s*$/.test(before) || /return\s*$/.test(before)) continue;
        offenders.push(`${file.slice(SRC.length + 1)}:${index + 1}  ${line.trim().slice(0, 60)}`);
      }
    });
  }
  assert.deepEqual(offenders, [],
    "这些调用没 await —— Promise 恒为真值，确认框等于被跳过，动作会直接执行：\n" + offenders.join("\n"));
});
