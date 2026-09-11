/**
 * 主题 × 角色的对比度自检。
 *
 * 为什么要脚本而不是眼看：本仓踩过两次同类的坑——一次是「白字被重映射成中灰，按钮
 * 整片看不见」，一次是「边栏永远是深色，导航却用了给浅底准备的墨色，四个主题里三个看不清」。
 * 两次都是肉眼在某一个主题下看着没问题就过了。对比度是能算的，那就算。
 *
 * 判据用 WCAG AA：正文 4.5:1，大字（≥24px 或 ≥18.7px 粗体）3:1。
 * 品牌色本身（--xm-brand）只按大字/色块要求，它不承载正文——这正是拆出
 * --accent-fill / --accent-text 的原因。
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const ROOT = path.resolve(import.meta.dirname, "..");

function luminance(hex) {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const f = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** 从 CSS 里取某个块的变量。同一个选择器出现多次就**全部合起来**。
 *
 * 原来这里是 `indexOf` —— 只读第一个匹配的块。而 styles.css 里有**两个** `:root {`：
 * 第一个是纸面那套（ink / paper / accent），第二个（5800 行附近）是深色舱体那套
 * （--deck-*）。于是**整套深色语言从来没进过这个检查** ——
 * 而深底上的对比度恰恰是最容易出事的地方：这个仓踩过的两次坑（白字被重映射成
 * 中灰、导航用了给浅底准备的墨色）都在深底上。
 */
function readBlock(css, selector) {
  const out = {};
  let from = 0;
  for (;;) {
    const at = css.indexOf(selector, from);
    if (at < 0) return out;
    const open = css.indexOf("{", at);
    const close = css.indexOf("}", open);
    if (open < 0 || close < 0) return out;
    for (const line of css.slice(open + 1, close).split(";")) {
      const m = line.match(/(--[\w-]+)\s*:\s*([^;]+)/);
      if (m) out[m[1]] = m[2].trim();
    }
    from = close + 1;
  }
}

const styles = await readFile(path.join(ROOT, "apps/web/src/styles.css"), "utf8");
const tokens = await readFile(path.join(ROOT, "apps/web/src/brand-tokens.css"), "utf8");
const platform = readBlock(tokens, ":root");
const base = { ...platform, ...readBlock(styles, ":root {") };

function resolve(vars, value, depth = 0) {
  if (!value || depth > 6) return null;
  const m = value.match(/var\((--[\w-]+)/);
  if (!m) return /^#[0-9a-f]{6}$/i.test(value.trim()) ? value.trim() : null;
  return resolve(vars, vars[m[1]], depth + 1);
}

const THEMES = ["paper", "contrast", "warm", "night"];

/** [前景 token, 背景 token, 说明, 最低要求] */
const PAIRS = [
  ["--ink", "--paper", "正文 on 纸面", 4.5],
  ["--ink-body", "--paper", "次级正文 on 纸面", 4.5],
  ["--ink-faint", "--paper", "弱化文字 on 纸面", 4.5],
  ["--ink", "--surface-soft", "正文 on 浅底", 4.5],
  ["--accent-text", "--paper", "强调文字 on 纸面", 4.5],
  ["--on-accent", "--accent-fill", "强调底上的字", 4.5],
  ["--on-dark", "--sidebar", "边栏正文", 4.5],
  ["--on-dark-soft", "--sidebar", "边栏未选中项", 4.5],
  ["--blue", "--paper", "品牌色块 on 纸面（只按色块 3:1）", 3.0],
];

/** 深色舱体那套。**跟主题无关** —— 舱是一块屏幕，四个主题下它都是那个深色。
 *
 * 门槛按各自真正的角色定，不是一律 4.5：
 *   - ink / soft / faint 承载正文与说明 → 4.5
 *   - gold 是舱里的主动作与强调 → 承载文字，4.5
 *   - red / green 只染涨跌那两个数，而那两个数是 --fs-head（19px）加粗 →
 *     WCAG 的「大字」档 3.0。**这不是放水**：CSS 里那两个类只出现在加粗大号处，
 *     哪天有人拿它去染小字，就该在这里把门槛改回 4.5，而不是把这行删掉。
 *   - mid 是记号色（色阶中点、条形底），从不承载文字，所以不在这张表里。
 */
const DECK_PAIRS = [
  ["--deck-ink", "--deck-bg", "舱内正文 on 舱面", 4.5],
  ["--deck-ink", "--deck-panel", "舱内正文 on 舱内卡", 4.5],
  ["--deck-soft", "--deck-bg", "舱内次级 on 舱面", 4.5],
  ["--deck-soft", "--deck-panel", "舱内次级 on 舱内卡", 4.5],
  ["--deck-faint", "--deck-bg", "舱内说明 on 舱面", 4.5],
  // .chain-boundary / .screen-strategy-off 就是这个组合 —— 说明文字压在舱内卡上
  ["--deck-faint", "--deck-panel", "舱内说明 on 舱内卡", 4.5],
  ["--deck-gold", "--deck-bg", "舱内主动作/强调", 4.5],
  ["--deck-gold", "--deck-panel", "舱内主动作 on 舱内卡", 4.5],
  ["--deck-red", "--deck-bg", "涨（大号加粗，按 3:1）", 3.0],
  ["--deck-green", "--deck-bg", "跌（大号加粗，按 3:1）", 3.0],
];

let failures = 0;

function check(vars, pairs) {
  for (const [fgKey, bgKey, label, min] of pairs) {
    const fg = resolve(vars, vars[fgKey]);
    const bg = resolve(vars, vars[bgKey]);
    if (!fg || !bg) {
      console.log(`  ⚠️  ${label}：解不出色值（${fgKey}=${vars[fgKey]} / ${bgKey}=${vars[bgKey]}）`);
      failures += 1;
      continue;
    }
    const r = ratio(fg, bg);
    const ok = r >= min;
    if (!ok) failures += 1;
    console.log(`  ${ok ? "✅" : "❌"} ${label.padEnd(26)} ${r.toFixed(2)}:1（需 ${min}）  ${fg} on ${bg}`);
  }
}

for (const theme of THEMES) {
  const vars = theme === "paper" ? base : { ...base, ...readBlock(styles, `:root[data-theme="${theme}"]`) };
  console.log(`\n主题 ${theme}`);
  check(vars, PAIRS);
}

// 舱体只查一遍：它的四层深色不随主题变（舱是一块屏幕，翻到哪个主题都是那块屏幕）。
console.log("\n深色舱体（不随主题变）");
check(base, DECK_PAIRS);

console.log(failures === 0 ? "\n全部达标 ✅" : `\n${failures} 项未达标 ❌`);
process.exit(failures === 0 ? 0 : 1);
