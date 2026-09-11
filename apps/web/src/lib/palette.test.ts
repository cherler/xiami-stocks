/**
 * 配色守门：**朱（批注）跟市场红（涨）必须分得开。**
 *
 * ## 这里原来是个真雷
 *
 * --cinnabar 同时在干两件相反的事：.quote-up 用它表示「涨」（好消息），
 * .evidence-card--counter 用它表示「反证」（坏消息）。同一个红，同一页上，
 * 两个相反的意思——而这个产品的全部价值就在于让人看清「这条对我不利」。
 *
 * 拆成两个之后，真正的风险不是拆错，是**日后有人把它们调回相近**：
 * 页面上看不出任何异常，只是反证不再刺眼了，而没人会发现。
 *
 * 所以这里量的是可分辨度而不是"是不是两个变量"：
 * ΔE（OKLab 近似，×100）低于 8 就是并排放着分不出来，等于没拆。
 * 现在 #8f2d24 vs #bd493a 是 14.8。
 *
 * ## 同时守住对比度
 *
 * 朱要承载正文（「这条踩到了你写的认错条件」），四套主题的纸面上都要 ≥4.5:1。
 * 深色主题必须反过来提亮：#8f2d24 压在 #16222a 上只剩 1.98:1，读不出来。
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

const CSS = readFileSync(join(import.meta.dirname, "..", "styles.css"), "utf8");

function rgb(hex: string) {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}
function lin(c: number) { return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }
function luminance(hex: string) {
  const [r, g, b] = rgb(hex).map(lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
function lab(hex: string) {
  const [r, g, b] = rgb(hex).map(lin);
  const x = 0.4124 * r + 0.3576 * g + 0.1805 * b;
  const y = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const z = 0.0193 * r + 0.1192 * g + 0.9505 * b;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const [fx, fy, fz] = [f(x / 0.95047), f(y), f(z / 1.08883)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}
function deltaE(a: string, b: string) {
  return Math.hypot(...lab(a).map((v, i) => v - lab(b)[i]));
}

/** 读某个外观块里的变量；没写就落回 :root。
 *
 * 2026-08-16 起本仓有两条轴，各占一个属性（见 App.tsx 里 THEMES 上面那段）：
 *   data-theme  light | dark      ← 平台开关（账户中心 › 设置 › 外观）
 *   data-look   contrast | warm   ← 本仓自己的浅色变体
 * 所以这里要按选择器名去找，不能再假定都挂在 data-theme 上。 */
function token(name: string, selector?: string): string {
  const block = selector
    ? CSS.slice(CSS.indexOf(`:root[${selector}] {`))
    : CSS;
  const hit = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block);
  assert.ok(hit, `找不到 --${name}${selector ? `（${selector}）` : ""}`);
  return hit![1];
}

test("朱跟市场红分得开", () => {
  const distance = deltaE(token("zhu"), token("cinnabar"));
  assert.ok(distance >= 8,
    `朱 ${token("zhu")} 与市场红 ${token("cinnabar")} 的 ΔE 只有 ${distance.toFixed(1)}。\n` +
    "低于 8 就是并排放着分不出来——而一个表示「涨」、一个表示「你的判断被推翻了」，\n" +
    "混在一起页面上看不出任何异常，只是反证不再刺眼了。");
});

test("朱在四套外观上都读得出来", () => {
  // 深色下的朱必须是另一个方向（提亮），所以各自取各自的纸面
  const grounds: [string | undefined, string][] = [
    [undefined, "#f7f8f6"],                  // 纸感（默认）
    ['data-look="contrast"', "#ffffff"],
    ['data-look="warm"', "#fbf7f0"],
    ['data-theme="dark"', "#16222a"],
  ];
  for (const [selector, paper] of grounds) {
    const value = token("zhu", selector);
    const level = contrast(value, paper);
    assert.ok(level >= 4.5,
      `${selector ?? "默认"} 的朱 ${value} 压在 ${paper} 上只有 ${level.toFixed(2)}:1。\n` +
      "它要承载正文（「这条踩到了你写的认错条件」），低于 4.5 就是看不清。");
  }
});

test("深浅那一档说的是平台的话", () => {
  // **这一条守的是这次实测出来的那个毛病。** 平台开关写的是 light/dark，
  // 而本仓原来往同一个属性上写 paper/night —— 于是 chrome.css 里
  // `[data-theme="dark"]` 永远匹配不到、`:not([data-theme="light"])` 永远匹配得到，
  // 页眉和页面各走各的：系统深色时页面是浅的、页眉是深的。
  assert.ok(CSS.includes(':root[data-theme="dark"]'),
    "深色块必须挂在平台词汇 data-theme=\"dark\" 上，页眉才跟得上");
  assert.ok(!/:root\[data-theme="(night|paper|contrast|warm)"\]/.test(CSS),
    "data-theme 只许放平台词汇（light/dark）；本仓自己的变体走 data-look");
});

test("红色的数字只表示涨", () => {
  // 朱只走线和边注。**一旦有人用它去染一个数字**，页面上就同时存在
  // 两种红数字，而读的人没有办法知道哪个是哪个。
  const guilty = /\.(quote|num|value|metric)[a-z-]*\s*{[^}]*color:\s*var\(--zhu\)/.exec(CSS);
  assert.equal(guilty, null,
    `朱被用来染数字了：${guilty?.[0]}\n` +
    "页面上任何一个红色的数字都只应该意味着「涨」。批注走线和边注。");
});

test("圆角只有三档，而且 --r-card 指向品牌令牌不另写一份", () => {
  // `--xm-radius-lg` 来自主站的品牌令牌（sync-brand-tokens 同步过来），
  // `--r-card` 是本仓用的名字。**两个名字各写一个数的话，改一处就错位** ——
  // 而错位的圆角没有任何地方会响：公司卡片是方的、面板是圆的，就是这么来的。
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.match(css, /--r-card: var\(--xm-radius-lg\)/,
    "--r-card 又写死成一个数了 —— 它要指向品牌令牌");
  const steps = [...css.matchAll(/^\s*--r-(well|card|deck):/gm)].map((m) => m[1]);
  assert.deepEqual(steps.sort(), ["card", "deck", "well"],
    `圆角档位变了：${steps.join("、")} —— 三档以外的圆角会让层级读不出来`);
});

test("状态色不许另写字面色值，红色的数字只能表示涨", () => {
  // ── 这一条守什么 ────────────────────────────────────────────────
  // 公司页顶部那条研究状态原来是四个字面色值，每一个都在重复一个已有的语义 token，
  // 值还都差一点点：good #27765d vs --jade ΔE 1.8、warn #9a661c vs --mark-ink 4.6。
  // ΔE 低于 8 就是并排看分不出来 —— **看不出差别，却要改四个地方**。
  //
  // 更要紧的是 risk：#aa4038 跟市场红 --cinnabar 只差 ΔE 4.5，于是
  // 「需留意 2」这个数读起来是"涨"。而 styles.css 开头立着一条规矩：
  // 「朱只走线和边注，从不用来染数字；页面上任何一个红色的数字永远只意味着涨。」
  // **按行首选择器取，不用 indexOf 划区间。**
  // 划区间的第一版当场就瞎了：舱头那边也有一组 `.detail-deck
  // .research-summary-metric--*`，`indexOf` 找到的是那一份，于是区间横跨四千行、
  // 把全站的色值都扫了进来。选择器前缀是唯一稳的锚。
  const rules = CSS.split("\n").filter((line) =>
    /^\.research-summary-metric--/.test(line));
  assert.ok(rules.length >= 3, `只找到 ${rules.length} 条状态色规则，这个守卫自己瞎了`);
  const literals = rules.join("\n").match(/#[0-9a-f]{3,8}\b/gi) ?? [];
  assert.deepEqual(literals, [],
    `状态色写了字面值 ${literals.join("、")} —— 指向已有的语义 token，不要另写一份`);

  const paper = rules.join("\n");
  // risk 那一格靠形（左缘一条朱），不靠给数字染色。
  // 同样只认行首那一条 —— 舱头里也有一条 `.detail-deck ....--risk::before`
  // （深底上朱只有 1.4:1，那边用金），indexOf 会先撞上它。
  const rail = /^\.research-summary-metric--risk::before \{([^}]*)\}/m.exec(CSS);
  assert.ok(rail, "找不到 risk 那条左缘 —— 状态又回到给数字染色了？");
  assert.match(rail![1], /background: var\(--zhu\)/,
    "risk 那一格要靠左缘一条朱来标，不是把数字染红");
  assert.match(paper, /--risk b \{ color: var\(--ink\)/,
    "risk 的数字必须是墨色 —— 红色的数字只能表示涨");
});

test("绿只留给主动作：次级动作退成墨色，hover 是同一个绿更深", () => {
  // 一屏上十几处品牌绿，绿就不再意味着"按这里会发生一件事"，
  // 只意味着"这里可以点"—— 而主动作那颗绿底按钮就此淹没在里面。
  const secondary = CSS.slice(CSS.indexOf(".text-button, .back-link {"),
                              CSS.indexOf(".ledger-row, .event-item, .watch-row--button"));
  assert.ok(secondary.length > 80, "找不到 .text-button 那一段");
  assert.match(secondary, /color: var\(--ink-body\)/, "次级动作用墨色，不用品牌绿");
  assert.ok(!/var\(--accent-text\)/.test(secondary),
    "次级动作又变回品牌绿了 —— 绿只留给 .page-action");
  // 深底上仍然是金：墨色压在 #102a35 上看不见
  assert.match(secondary, /\.deck \.text-button[\s\S]*?var\(--deck-gold\)/,
    "舱里的次级动作必须还是金色");

  // hover 换色相不是 hover，是换了个按钮（原来 #097067 → #264c65，ΔE 11.5）
  const hover = CSS.match(/\.page-action:hover \{[^}]*\}/)?.[0] ?? "";
  assert.ok(!/#[0-9a-f]{6}/i.test(hover),
    `.page-action:hover 写了字面色值：${hover} —— 用 --xm-brand-strong`);
  assert.match(hover, /--xm-brand-strong/);

  // 展开器一个都不许还是绿的。
  // **`summary` 要当元素名匹配，不能当子串** —— `.research-summary-metric--accent`
  // 这个类名里也有 summary，而它是「证据」那个计数，该留着品牌绿。
  // 我用 sed 扫的时候正是在这儿改错了一处，所以这里的正则要盯住词边界。
  const isToggle = /(^|[\s>])summary(?![-\w])/;
  const greenToggles = CSS.split("\n").filter((line) =>
    isToggle.test(line.split("{")[0] ?? "") && line.includes("var(--accent-text)"));
  assert.deepEqual(greenToggles, [], "还有展开器是品牌绿的");
});

test("公司页顶部是深色舱头，涨跌是大号加粗", () => {
  // 「今天」「找票」开场就是一块深色屏幕，公司档案原来开场是白底加一条绿下划线。
  // 同一个产品两个视觉世界，而公司档案是停留最久的那一页。
  const app = readFileSync(join(import.meta.dirname, "..", "App.tsx"), "utf8");
  const deck = app.indexOf('className="detail-deck deck"');
  assert.ok(deck > 0, "公司页顶部的 .detail-deck deck 包裹层没了 —— 舱头退回白底了");
  // 名字和页签必须都在这一层里面：它们是同一件事（你在看哪家公司）
  const hero = app.indexOf('className="detail-hero"', deck);
  const tabs = app.indexOf('className="detail-tabs"', deck);
  const close = app.indexOf("</div>", Math.max(hero, tabs));
  assert.ok(deck < hero && hero < tabs && tabs < close,
    "detail-hero 和 detail-tabs 必须都包在 .detail-deck 里 —— 少一个就露出一截白底");

  const block = CSS.slice(CSS.indexOf(".detail-deck {"), CSS.indexOf(".revision-actions {"));
  assert.ok(block.length > 200, "找不到 .detail-deck 那一段");
  // **涨跌必须是大号加粗。** --deck-red 压在舱面上 4.41:1：
  // 小字要 4.5 不够，只有 ≥18.66px 加粗才落进 WCAG 的「大字」档（3:1）。
  // --fs-head 是 19px。降到 --fs-lead（16px）就是悄悄地不达标了。
  assert.match(block, /\.detail-deck \.detail-quote \{[^}]*font-size: var\(--fs-head\)/,
    "舱头里的价格要 --fs-head（19px）—— 小字压在 --deck-red 上不到 4.5:1");
  assert.match(block, /\.detail-deck \.detail-quote em \{[^}]*font-weight: 700/,
    "涨跌那个百分比也要加粗，不然它单独掉出大字档");
  assert.ok(!/\.detail-quote[^}]*font-size: var\(--fs-(lead|small|body)\)/.test(block),
    "舱头里不许把涨跌降成小字 —— 那会悄悄地不达标（4.41:1 < 4.5）");
  // 选中的页签用金，不用品牌绿（青绿压在 #102a35 上只有 2.4:1）
  assert.match(block, /\.detail-tab--on \{[^}]*border-bottom-color: var\(--deck-gold\)/);
});

test("字号只有一套阶梯，而且每一档都真的定义过", () => {
  // ── 这一条守什么 ────────────────────────────────────────────────
  // 使用者的说法是「字体忽大忽小」。查出来两个原因，都不是审美问题：
  //
  // 1. **用了从来没定义过的档位。** --fs-tiny 12 处、--fs-micro 2 处、
  //    --fs-section 1 处，三个都没有定义。CSS 引用未定义变量会把整条
  //    font-size 丢掉，于是那 15 个元素**继承父级字号** —— 同一排标签，
  //    有的 11px 有的 14px，取决于它挂在谁下面。
  // 2. **两套阶梯并存。** 主站那套（--xm-fs-*：10/11/12/13/15/24）和本仓这套
  //    （--fs-*：10/11/12.5/14/16/19/25）同时活着，而 assess-block 那张卡
  //    一张里就同时用了两套的四档。
  const used = new Set([...CSS.matchAll(/var\(--(fs-[a-z]+)\)/g)].map((m) => m[1]));
  const defined = new Set([...CSS.matchAll(/^\s*--(fs-[a-z]+):/gm)].map((m) => m[1]));
  const missing = [...used].filter((name) => !defined.has(name)).sort();
  assert.deepEqual(missing, [],
    `这些字号用了但没定义：${missing.join("、")} —— ` +
    "CSS 会把整条 font-size 丢掉，元素改成继承父级，看起来就是「忽大忽小」");

  // 主站那套字号不许再出现在本仓样式里：阶梯不一样，混用就是两套并存
  const strays = [...CSS.matchAll(/var\(--xm-fs-[a-z]+\)/g)].map((m) => m[0]);
  assert.deepEqual(strays, [],
    `还在用主站那套字号：${[...new Set(strays)].join("、")} —— 阶梯跟本仓这套不同`);
});

test("中性面不许偏绿", () => {
  // 使用者：「我不喜欢那个淡绿色的输入框背景。而现在那那都是淡绿色。
  // 跟带个绿帽子一样难受死了」。--surface-soft 就是它，被当成输入框、卡片、
  // 徽章、表头的填充用了近百处；它绿，整页就绿。
  //
  // 判据可以算：G 比 B 高就是绿偏（底色里蓝最少）。中性面要么持平，
  // 要么往冷里偏一点点（跟正文墨色 #14202a 同向）—— 那是"选过的中性"，
  // 而不是"不小心带了个色"。warm 那套是刻意的暖，不在这条里。
  for (const [name, selector] of [["surface-page", undefined],
                                  ["surface-sunken", undefined]] as const) {
    const hex = token(name, selector);
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
    assert.ok(g - b <= 0,
      `--${name} = ${hex} 偏绿（G ${g} 比 B ${b} 高 ${g - b}）—— ` +
      "它是输入框和卡片的底色，绿了整页都绿");
    assert.ok(Math.abs(g - r) <= 4, `--${name} = ${hex} 色偏太重，中性面要中性`);
  }
});

test("没有一个 CSS 变量是用了却从来没定义过的", () => {
  // ── 这一条是这轮 UI 复查里最值钱的一个发现 ────────────────────────
  //
  // 实测：12 个变量、32 处声明是**死的** —— 写了，但浏览器把整条声明丢掉。
  // 症状分两种，两种都不会报错，也都不会被任何测试发现：
  //
  //   font-size: var(--fs-tiny)        → 那 15 个元素改成继承父级字号
  //                                      （使用者：「字体忽大忽小」）
  //   color: var(--ink-1, #1f2933)     → 永远用那个写死的浅色兜底，
  //                                      **深色主题下直接看不见**
  //                                      （反证条件那两条在深色下整个消失，就是它）
  //
  // 带兜底的那种更阴险：浅色下一切正常，只有深色主题坏，而深色主题没人天天看。
  const tokens = readFileSync(join(import.meta.dirname, "..", "brand-tokens.css"), "utf8");
  const defined = new Set([
    ...[...CSS.matchAll(/--([a-z0-9-]+):/g)].map((m) => m[1]),
    ...[...tokens.matchAll(/--([a-z0-9-]+):/g)].map((m) => m[1]),
  ]);
  // 没有兜底的：整条声明会被丢掉
  const bare = [...new Set([...CSS.matchAll(/var\(--([a-z0-9-]+)\)/g)].map((m) => m[1]))]
    .filter((name) => !defined.has(name)).sort();
  assert.deepEqual(bare, [],
    `这些变量用了但没定义：${bare.join("、")}\n` +
    "CSS 会把整条声明丢掉 —— 字号变成继承父级，颜色变成继承或透明，而且不报错。");

  // 有兜底的：允许，但兜底必须是变量而不是写死的色值 ——
  // 写死的色值不会跟着主题翻，深色下就是错的
  const frozen = [...CSS.matchAll(/var\(--([a-z0-9-]+),\s*(#[0-9a-fA-F]{3,8})\)/g)]
    .filter((m) => !defined.has(m[1])).map((m) => `--${m[1]}→${m[2]}`);
  assert.deepEqual([...new Set(frozen)], [],
    `这些变量没定义，兜底还写死了色值：${[...new Set(frozen)].join("、")}\n` +
    "写死的颜色不会跟着主题翻 —— 浅色下看着正常，深色下是错的。");
});

test("同一个选择器不许在两处设同一个属性", () => {
  // ── 这一条守什么 ────────────────────────────────────────────────
  //
  // 实测：2996 条顶层规则里，57 个选择器被定义了不止一次，
  // 其中 **43 个真的在两处设了同一个属性**（一共 104 条声明）。
  // 同选择器、同权重 → 后者胜，所以**前面那一份写了等于没写**。
  //
  // 症状是"改了没生效"：你打开样式表搜到 `.thesis-list-row`，改了 padding，
  // 刷新页面没有任何变化 —— 因为四千行之后还有一份。而它不报错、不警告，
  // 唯一的表现是你以为自己改错了别的地方。
  //
  // 只查**同一个属性在多处**，不查"选择器出现两次"：
  // 后者是正常的（一处布局、一处主题覆盖），只有撞上同一个属性才有害。
  const blocks: Array<[string, string]> = [];
  let i = 0;
  while (i < CSS.length) {
    const ch = CSS[i];
    if (ch === "@") {                       // @media 等整块跳过
      const open = CSS.indexOf("{", i);
      if (open < 0) break;
      let depth = 1, k = open + 1;
      while (k < CSS.length && depth) { depth += (CSS[k] === "{" ? 1 : CSS[k] === "}" ? -1 : 0); k++; }
      i = k; continue;
    }
    if (ch === "{") {
      const sel = CSS.slice(0, i).split("}").pop()!.split("*/").pop()!.trim();
      const close = CSS.indexOf("}", i);
      if (close < 0) break;
      if (sel && !sel.startsWith(":root")) blocks.push([sel, CSS.slice(i + 1, close)]);
      i = close + 1; continue;
    }
    i++;
  }
  const seen = new Map<string, Map<string, number>>();
  for (const [sel, body] of blocks) {
    const props = seen.get(sel) ?? new Map<string, number>();
    for (const m of body.matchAll(/([a-z-]+)\s*:/g)) {
      if (m[1] === "http" || m[1] === "https") continue;   // 注释里的 URL
      props.set(m[1], (props.get(m[1]) ?? 0) + 1);
    }
    seen.set(sel, props);
  }
  const clashes: string[] = [];
  for (const [sel, props] of seen) {
    const dup = [...props].filter(([, n]) => n > 1).map(([p]) => p);
    // 同一个块里自己重复是合法的（渐进增强：先纯色再渐变），
    // 所以只在这个选择器**出现过多次**时才算
    if (dup.length && blocks.filter(([s]) => s === sel).length > 1) {
      clashes.push(`${sel} → ${dup.slice(0, 3).join("、")}`);
    }
  }
  assert.deepEqual(clashes, [],
    `这些选择器在两处设了同一个属性，前面那份写了等于没写：\n  ${clashes.join("\n  ")}\n` +
    "症状是「改了没生效」，而且不报错 —— 你只会以为自己改错了地方。");
});

test("间距阶梯存在，而且新写的间距不许再逐像素拍", () => {
  // ── 这一条守什么 ────────────────────────────────────────────────
  //
  // 使用者：「靠边的距离也是忽近忽远」。量出来不是感觉：
  // padding 32 种像素值（1066 处）、margin 41 种（780 处）、gap 22 种（618 处），
  // 而且是「9 / 10 / 11 / 12 / 13 / 14」这种逐像素连续的取值 —— 没有阶梯。
  //
  // 阶梯是从现有分布的峰值上取的（10 / 14 / 18 各被用了两百来处），
  // ±1px 覆盖 92%。**按属性分开命名**：同一个数字在 padding / gap / margin 上
  // 含义不一样，共用一个名字会让人在该换档时不换。
  //
  // **存量 2400 多处不做全量替换。** 今天验证过，大范围机械改样式要三条独立
  // 验证路径才敢说没坏，而这件事的收益只是"以后一致"，不值那个风险。
  // 所以这条守的是「阶梯还在」，不是「所有地方都用了阶梯」——
  // 后者会在存量清完之前一直红，而一条长期红着的守卫等于没有守卫。
  for (const prefix of ["pad", "gap", "stack"]) {
    const steps = [...CSS.matchAll(new RegExp("--" + prefix + "-([0-9]+):", "g"))].map((m) => Number(m[1]));
    assert.ok(steps.length >= 6,
      `--${prefix}-* 阶梯没了或者不足六档（现在 ${steps.length} 档）`);
    // 阶梯必须是递增的、没有重复档
    assert.deepEqual([...steps].sort((a, b) => a - b), steps,
      `--${prefix}-* 的档位没有按大小排 —— 排乱了就没人看得出下一档是哪个`);
    assert.equal(new Set(steps).size, steps.length, `--${prefix}-* 有重复档位`);
  }
  // 阶梯本身不许写成别的单位或表达式：它要能被一眼读成"第几档"
  const block = CSS.slice(CSS.indexOf("--pad-2:"), CSS.indexOf("--stack-36:") + 40);
  assert.ok(!/calc\(|var\(/.test(block),
    "间距阶梯里出现了 calc/var —— 档位要是字面像素值，不然读不出层级");
});
