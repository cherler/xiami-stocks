/**
 * 样式冲突守门：**同一个类名不许被两处各定义一套网格。**
 *
 * 这条规则是被实测逼出来的。`.peer-row` 在 styles.css 里出现了三次：
 * 同业对照表要 12 列，而另外两处（PeerPosition 组件，还是逐字重复的两份）
 * 各定义了 3 列、排在更后面、同等特异性——于是 12 个字段被挤进 3 列、
 * 折成 4 行，「对照」这件事完全没法看。
 *
 * 这类 bug 最难发现的地方在于：**页面不报错，元素也都在**，
 * 只是排版看着"有点怪"。而它是一行 CSS 覆盖了另一行的结果。
 *
 * 所以扫源码：凡是给某个类名写了 grid-template-columns 的顶层规则，
 * 同一个类名不许出现第二处（媒体查询里的响应式覆盖是正常的，跳过）。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const CSS = join(import.meta.dirname, "..", "styles.css");

test("同一个类名不许在两处各定义一套 grid-template-columns", () => {
  const source = readFileSync(CSS, "utf8");
  const lines = source.split("\n");
  const owners = new Map<string, number[]>();
  let depth = 0;

  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    // 媒体查询内部是响应式覆盖，本来就该重定义——只看顶层规则。
    //
    // **必须数花括号，不能只认「单独一行的 }」。** 这个文件里大量规则写成一行
    // （`@media (max-width: 720px) { .pp-row { … } }`），只认独立的 } 的话
    // 深度永远减不回来，从第一处单行 @media 起所有规则都被当成"在媒体查询里"
    // 跳过——**测试于是永远是绿的，因为它什么都没检查**。我第一版就是这么写的。
    const wasTopLevel = depth === 0;
    const atMedia = /^\s*@media/.test(line);
    if (atMedia) depth++;
    depth += (line.match(/{/g) ?? []).length - (atMedia ? 1 : 0);
    depth -= (line.match(/}/g) ?? []).length;
    if (depth < 0) depth = 0;
    if (!wasTopLevel && !(atMedia && depth === 0)) continue;
    if (atMedia) continue;

    if (!line.includes("grid-template-columns")) continue;
    const selector = line.split("{")[0].trim();
    // 只管单一类选择器（.foo），复合选择器本来就是有意的细化
    const match = /^\.([a-z0-9_-]+)$/i.exec(selector);
    if (!match) continue;
    const list = owners.get(match[1]) ?? [];
    list.push(index + 1);
    owners.set(match[1], list);
  }

  const clashes = [...owners.entries()].filter(([, at]) => at.length > 1);
  assert.deepEqual(
    clashes.map(([name, at]) => `.${name} 在第 ${at.join(" / ")} 行各定义了一次列`),
    [],
    "同一个类名两处各定义一套网格，后面那处会静默盖掉前面的——\n" +
    "页面不报错、元素都在，只是列数变了，排版看着「有点怪」。");
});
