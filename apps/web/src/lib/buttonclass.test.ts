/**
 * 按钮守门：**每个 `<button>` 至少要命中一条真的存在的样式类。**
 *
 * ## 这条是被一次深色主题截图逼出来的
 *
 * 我给新页面的主动作按钮写了 `className="primary-button"` —— 而全站 CSS 里
 * **一条 `.primary-button` 都没有**（主动作叫 `.page-action`）。
 *
 * 后果不是报错，是按钮拿了浏览器默认样式：浅色下勉强能看，深色下是一块
 * 糊掉的浅蓝方块，字读不出来。tsc 不管（className 就是个字符串），
 * 单元测试不管，构建也不管 —— 只有真的在深色下看一眼才发现。
 *
 * ## 为什么只查 button，不查所有 className
 *
 * 全仓有二十来个「用了但 CSS 里没有」的类名，绝大多数是**语义挂钩**
 * （`ledger-panel`、`event-panel`、`promise-ledger`）：它们不需要自己的规则，
 * 存在的意义是让人和将来的样式找得到这一块。拿它们报错只会让这条守卫被关掉。
 *
 * 而按钮不一样：**一个没有样式的按钮一定是错的**。它是要被点的东西，
 * 没有样式就意味着没有可点的外观、没有焦点态、没有深色适配。
 * 所以范围收到 button，判据收到「一条都没命中」。
 */

import { readFileSync } from "node:fs";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const SRC = join(import.meta.dirname, "..");
const CSS = readFileSync(join(SRC, "styles.css"), "utf8");

/** styles.css 里出现过的所有类名。 */
function definedClasses(): Set<string> {
  return new Set(Array.from(CSS.matchAll(/\.([a-zA-Z][\w-]*)/g), (m) => m[1]));
}

function tsxFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) walk(path);
      else if (entry.name.endsWith(".tsx")) out.push(path);
    }
  };
  walk(SRC);
  return out;
}

/** `<button ... className={...}>` 里的静态类名。模板插值那一段挖掉。 */
function buttonClasses(source: string): { raw: string; classes: string[] }[] {
  const out: { raw: string; classes: string[] }[] = [];
  for (const match of source.matchAll(/<button\b[\s\S]*?>/g)) {
    const tag = match[0];
    const attr = tag.match(/className=(?:"([^"]*)"|\{`([^`]*)`\})/);
    if (!attr) continue;
    const raw = attr[1] ?? attr[2] ?? "";
    // `${...}` 是条件类，静态部分之外的先不判 —— 只要静态部分有一条命中就够
    const classes = raw.replace(/\$\{[^}]*\}/g, " ").split(/\s+/).filter(Boolean);
    out.push({ raw, classes });
  }
  return out;
}

test("每个按钮至少命中一条真的存在的样式类", () => {
  const defined = definedClasses();
  assert.ok(defined.has("page-action"), "读 styles.css 失败 —— 这条守卫自己瞎了");
  assert.ok(!defined.has("primary-button"),
    "现在真有 .primary-button 了？那这条守卫的来历要重写");

  const orphans: string[] = [];
  for (const file of tsxFiles()) {
    const source = readFileSync(file, "utf8");
    for (const { raw, classes } of buttonClasses(source)) {
      if (classes.length === 0) continue;             // 只有条件类，跳过
      if (classes.some((cls) => defined.has(cls))) continue;
      orphans.push(`${file.slice(SRC.length + 1)}: className="${raw}"`);
    }
  }
  assert.deepEqual(orphans, [],
    "这几个按钮的类名在 styles.css 里一条都找不到 —— 它们拿的是浏览器默认样式，"
    + "深色主题下基本读不出来：\n  " + orphans.join("\n  "));
});
