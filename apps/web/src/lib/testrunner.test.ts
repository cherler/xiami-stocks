/**
 * 每个测试文件都要真的被跑到。
 *
 * 运行器是 `node --test src/lib/*.test.ts`（见 apps/web/package.json）。
 * 写在 src 下别处的 `*.test.ts` **不会报错，只是静静地跳过** ——
 * 你以为加了覆盖，其实一条都没跑。
 *
 * 2026-08-18 我自己就把一份超时测试写在了 src/api.timeout.test.ts，
 * 门禁全绿，而那个文件从头到尾没执行过一行。
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const SRC = join(import.meta.dirname, "..");
const LIB = join(SRC, "lib");

function testFilesUnder(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      found.push(...testFilesUnder(full));
    } else if (entry.endsWith(".test.ts") || entry.endsWith(".test.tsx")) {
      found.push(full);
    }
  }
  return found;
}

test("没有测试文件放在运行器够不着的地方", () => {
  const stray = testFilesUnder(SRC).filter((f) => join(f, "..") !== LIB);
  assert.deepEqual(stray, [],
    "这些测试不在 src/lib/ 下，`node --test src/lib/*.test.ts` 跑不到它们：\n  "
    + stray.map((f) => f.slice(SRC.length + 1)).join("\n  ")
    + "\n挪进 src/lib/，或者把 package.json 里的 test 脚本改成能覆盖它们。");
});

test("运行器的 glob 还是我以为的那个", () => {
  // 上面那条判定建在这个 glob 上。脚本改了而判定没跟着改，等于没有判定。
  const pkg = readFileSync(join(SRC, "..", "package.json"), "utf8");
  assert.ok(pkg.includes("node --test src/lib/*.test.ts"),
    "test 脚本变了 —— 上面那条「没有测试文件放在运行器够不着的地方」要跟着改");
});
