/**
 * 市场色守门：**「涨」这一个意思，全站只准有一个红。**
 *
 * ## 这条为什么要用测试守，而不是靠约定
 *
 * 审这个仓的时候量出来：「涨」有五个红、「跌」有五个绿，散在
 * styles.css、chartTokens、简报图、驾驶舱、云图色阶里。而且是两种失败叠在一起——
 *
 *   - #bd493a 与 #b0402f 差 ΔE 3.4，#277b66 与 #2f7f68 差 ΔE 1.4：
 *     **看不出差别，却要改三个地方**。这种重复没有任何症状，只会在
 *     「改了颜色但有一处没跟上」时冒出来，而且那一处通常没人打开过。
 *   - #bd493a 与驾驶舱的 #ee6a52 差 ΔE 12.3：
 *     **同一个意思，翻一页就换个红**。这个有症状，但症状是「感觉不像一个产品」，
 *     没人会把它写成 bug 报上来。
 *
 * 两种都不会让任何页面报错，所以只能在这里钉住。
 *
 * ## 守四件事
 *
 * 1. 深底那份涨跌色，TS 与 CSS 两处必须一模一样（同一张卡片上，图靠 TS 上色、
 *    数字靠 CSS 上色——不一致就是同一个「涨」两个红）。
 * 2. 色阶结构：中点中性、明度单调、相邻等距。这三条任何一条破了，图就会说谎，
 *    而它看上去仍然是一张正常的云图。
 * 3. 色块上的字，沿整条色阶都读得了。原来写死白字，浅色档只有 1.11:1。
 * 4. 涨/平/跌三色在色觉障碍下两两分得开——它们是**贴在一起**的三段。
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

import { marketInk, marketRamp, rampColor, tileInk } from "../components/chartTokens.ts";

const HERE = import.meta.dirname;
const CSS = readFileSync(join(HERE, "..", "styles.css"), "utf8");

function rgb(hex: string) {
  const value = hex.replace("#", "");
  return [0, 2, 4].map((index) => parseInt(value.slice(index, index + 2), 16) / 255);
}
const toLinear = (channel: number) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);

function oklab(hex: string): [number, number, number] {
  const [red, green, blue] = rgb(hex).map(toLinear);
  const l = Math.cbrt(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue);
  const m = Math.cbrt(0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue);
  const s = Math.cbrt(0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue);
  return [
    0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
  ];
}
/** OKLab 距离 ×100。低于 8 就是并排放着分不出来。 */
function deltaE(first: string, second: string): number {
  const a = oklab(first);
  const b = oklab(second);
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]) * 100;
}
const lightness = (hex: string) => oklab(hex)[0] * 100;
const chroma = (hex: string) => Math.hypot(oklab(hex)[1], oklab(hex)[2]) * 100;

function luminance(hex: string) {
  const [red, green, blue] = rgb(hex).map(toLinear);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}
function contrast(first: string, second: string) {
  const [high, low] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (high + 0.05) / (low + 0.05);
}

/** 色觉障碍模拟（Viénot 1999，LMS 投影）。红绿轴塌掉之后还分不分得开。 */
function simulate(hex: string, kind: "protan" | "deutan" | "tritan"): [number, number, number] {
  const apply = (matrix: number[][], vector: number[]) =>
    matrix.map((row) => row[0] * vector[0] + row[1] * vector[1] + row[2] * vector[2]);
  const toLms = [[17.8824, 43.5161, 4.11935], [3.45565, 27.1554, 3.86714], [0.0299566, 0.184309, 1.46709]];
  const fromLms = [
    [0.0809444479, -0.130504409, 0.116721066],
    [-0.0102485335, 0.0540193266, -0.113614708],
    [-0.000365296938, -0.00412161469, 0.693511405],
  ];
  const projection = {
    protan: [[0, 2.02344, -2.52581], [0, 1, 0], [0, 0, 1]],
    deutan: [[1, 0, 0], [0.494207, 0, 1.24827], [0, 0, 1]],
    tritan: [[1, 0, 0], [0, 1, 0], [-0.395913, 0.801109, 0]],
  }[kind];
  const projected = apply(projection, apply(toLms, rgb(hex).map(toLinear)));
  return apply(fromLms, projected).map((value) => Math.min(1, Math.max(0, value))) as [number, number, number];
}
function deltaEUnderCvd(first: string, second: string): number {
  const asHex = (channel: number[]) =>
    "#" + channel.map((value) => {
      const encoded = value <= 0.0031308 ? 12.92 * value : 1.055 * value ** (1 / 2.4) - 0.055;
      return Math.round(Math.min(1, Math.max(0, encoded)) * 255).toString(16).padStart(2, "0");
    }).join("");
  return Math.min(...(["protan", "deutan", "tritan"] as const)
    .map((kind) => deltaE(asHex(simulate(first, kind)), asHex(simulate(second, kind)))));
}

function cssVar(name: string): string {
  // 取最后一次赋值：主题块会覆盖 :root，而驾驶舱那几个只在 .market-cockpit 里定义一次
  const hits = [...CSS.matchAll(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`, "g"))];
  assert.ok(hits.length > 0, `styles.css 里找不到 --${name}`);
  return hits[hits.length - 1][1].toLowerCase();
}

test("深底的涨跌色，TS 与 CSS 两处必须是同一个值", () => {
  // 同一张卡片上：云图的格子由 chartTokens 上色，「+1.84%」这种数字由
  // .quote-up/.quote-down 上色。两份漂开一点，页面不会报错，
  // 只是同一个「涨」在同一屏里成了两个红。
  assert.equal(cssVar("deck-red"), marketInk.ink.up, "--deck-red 与 marketInk.ink.up 不一致");
  assert.equal(cssVar("deck-green"), marketInk.ink.down, "--deck-green 与 marketInk.ink.down 不一致");
  // 图例那条渐变的中点：它要跟云图色阶的中点是同一个灰，
  // 否则图例说的「零在这里」跟图上画的零不是一个颜色。
  const middle = marketRamp.ink.diverging[Math.floor(marketRamp.ink.diverging.length / 2)];
  assert.equal(cssVar("deck-mid"), middle, "--deck-mid 与分歧色阶的中点不一致");
});

test("驾驶舱的 --cockpit-* 一律指向 --deck-*，不许写死色号", () => {
  // 首页那一块保留 --cockpit-* 只是为了不动它内部六十多处引用。
  // 一旦有人图省事在这里填回一个具体色号，两套语言就又开始各走各的了——
  // 而那正是这次要根治的问题。
  const block = CSS.slice(CSS.indexOf(".market-cockpit {"));
  const body = block.slice(0, block.indexOf("}"));
  const hardcoded = [...body.matchAll(/(--cockpit-[a-z-]+):\s*(#[0-9a-fA-F]{3,8})/g)]
    .map(([, name, value]) => `${name} 写死成了 ${value}`);
  assert.deepEqual(hardcoded, [], `改成 var(--deck-*)`);
});

test("纸面的涨跌色，TS 与 CSS 两处必须是同一个值", () => {
  assert.equal(cssVar("cinnabar"), marketInk.paper.up, "--cinnabar 与 marketInk.paper.up 不一致");
  assert.equal(cssVar("jade"), marketInk.paper.down, "--jade 与 marketInk.paper.down 不一致");
});

test("资金流的图例色块与柱子用的是同一支色阶", () => {
  // 图例的方块在 styles.css 里上色、柱子在 MarketCockpit 里上色。
  // 两份对不上，页面照样正常，只是**图例指错了柱子**——
  // 这种错没人会当场发现，但读图的人会一直读错。
  const swatches = ["is-super", "is-large", "is-medium", "is-small"].map((name) => {
    const hit = CSS.match(new RegExp(`\\.cockpit-flow-orders \\.${name} \\{ background: (#[0-9a-fA-F]{6}); \\}`));
    assert.ok(hit, `styles.css 里找不到 .${name} 的底色`);
    return hit[1].toLowerCase();
  });
  const fromRamp = [4, 3, 2, 1].map((index) => marketRamp.ink.sequential[index]);
  assert.deepEqual(swatches, fromRamp,
    "图例色块与 marketRamp.ink.sequential 取的档位对不上");
});

test("深底与纸面是同一个颜色的两个明度版本，不是两个颜色", () => {
  const hue = (hex: string) => {
    const [, a, b] = oklab(hex);
    return ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
  };
  for (const key of ["up", "down"] as const) {
    const drift = Math.abs(hue(marketInk.paper[key]) - hue(marketInk.ink[key]));
    assert.ok(drift <= 6,
      `${key} 的色相在纸面与深底之间差了 ${drift.toFixed(1)}°——超过 6° 就不是同一个颜色了`);
  }
});

test("分歧色阶的中点是中性的，不能是第三个色相", () => {
  for (const [ground, ramp] of Object.entries(marketRamp)) {
    const middle = ramp.diverging[Math.floor(ramp.diverging.length / 2)];
    // 原来驾驶舱的中点是 #294750，C=3.9 且偏蓝：从 -0.5% 走到 0% 时颜色由绿转蓝，
    // 而蓝在这张图上不表示任何东西，读者只会把它当成第三类。
    assert.ok(chroma(middle) < 4,
      `${ground} 分歧色阶的中点 ${middle} 彩度 ${chroma(middle).toFixed(1)}，不够中性`);
  }
});

test("色阶的明度是单调的（分歧色阶对称成 V/Λ）", () => {
  for (const [ground, ramps] of Object.entries(marketRamp)) {
    const sequential = ramps.sequential.map(lightness);
    const rising = sequential.every((value, index) => index === 0 || value > sequential[index - 1]);
    const falling = sequential.every((value, index) => index === 0 || value < sequential[index - 1]);
    assert.ok(rising || falling, `${ground} 顺序色阶的明度不单调：${sequential.map((v) => v.toFixed(0))}`);

    // 分歧色阶：从两端走向中点，明度必须一路同向。原来那条是 68 → 38 → 53，
    // 走到中点掉了 30 点又回升——人眼把亮度读成强度，于是 -0.1% 看起来比 -1.3% 还极端。
    const diverging = ramps.diverging.map(lightness);
    const middle = Math.floor(diverging.length / 2);
    const left = diverging.slice(0, middle + 1);
    const right = diverging.slice(middle);
    const monotone = (list: number[]) =>
      list.every((value, index) => index === 0 || value < list[index - 1])
      || list.every((value, index) => index === 0 || value > list[index - 1]);
    assert.ok(monotone(left) && monotone(right),
      `${ground} 分歧色阶的明度不是 V/Λ：${diverging.map((v) => v.toFixed(0))}`);
  }
});

test("色阶相邻两档的间距是均匀的", () => {
  for (const [ground, ramps] of Object.entries(marketRamp)) {
    for (const [kind, ramp] of Object.entries(ramps)) {
      const steps = ramp.slice(1).map((hex, index) => deltaE(ramp[index], hex));
      const [min, max] = [Math.min(...steps), Math.max(...steps)];
      assert.ok(min >= 8, `${ground}/${kind} 有一档跟前一档只差 ΔE ${min.toFixed(1)}，看不出台阶`);
      assert.ok(max / min <= 2.2,
        `${ground}/${kind} 台阶忽宽忽窄（${steps.map((v) => v.toFixed(0)).join(" / ")}）——间距不匀会被读成数值差距`);
    }
  }
});

test("色块上的字，沿整条色阶都读得了", () => {
  // 原来写死白字：市场云图页顺序色阶的前四档是浅蓝灰，白字压上去
  // 只有 1.11 / 1.39 / 1.90 / 2.89:1 —— 六档里四档读不了。
  //
  // 地板取 4.0 而不是 4.5：底色是中等亮度时，**任何**一种字都撑不出 4.5，
  // 换成纯黑最多也只有 4.46:1。这是色阶自身的物理上限，不是选色不用心。
  for (const [ground, ramps] of Object.entries(marketRamp)) {
    for (const [kind, ramp] of Object.entries(ramps)) {
      for (let step = 0; step <= 40; step += 1) {
        const fill = rampColor(step / 40, [0, 1], ramp);
        const ink = tileInk(fill);
        assert.ok(contrast(ink.strong, fill) >= 4.0,
          `${ground}/${kind} 在 ${(step / 40 * 100).toFixed(0)}% 处（${fill}）主文字只有 ${contrast(ink.strong, fill).toFixed(2)}:1`);
        assert.ok(contrast(ink.soft, fill) >= 3.0,
          `${ground}/${kind} 在 ${(step / 40 * 100).toFixed(0)}% 处（${fill}）次文字只有 ${contrast(ink.soft, fill).toFixed(2)}:1`);
      }
    }
  }
});

test("涨/平/跌三色在色觉障碍下两两分得开", () => {
  // 这三段是**贴在一起**的（市场脉搏那个圆环、简报的涨跌条），
  // 中间没有留白，分不开就是读不出比例。
  //
  // 红绿在色觉障碍下靠的只剩明度，所以「平」不能选一个跟红绿一样亮的中灰——
  // 原来驾驶舱用 #70858d，跟跌色在红色盲下只差 ΔE 4.3。
  for (const [ground, ink] of Object.entries(marketInk)) {
    for (const [first, second] of [["up", "flat"], ["up", "down"], ["flat", "down"]] as const) {
      const worst = deltaEUnderCvd(ink[first], ink[second]);
      assert.ok(worst >= 8,
        `${ground} 的 ${first}/${second}（${ink[first]} / ${ink[second]}）在色觉障碍下只差 ΔE ${worst.toFixed(1)}`);
    }
  }
});

test("顺序色阶的末档不能撞上灯塔金", () => {
  // 原来驾驶舱顺序色阶的末档是 #f0c66c，跟「已建档公司」的金色 #f2c86f
  // 差 ΔE 0.6 —— 等于同一个色。于是数值最高的那一格看起来像是你的自选股。
  for (const [ground, ramps] of Object.entries(marketRamp)) {
    const beacon = marketInk[ground as keyof typeof marketInk].beacon;
    for (const step of ramps.sequential) {
      assert.ok(deltaE(step, beacon) >= 8,
        `${ground} 顺序色阶的 ${step} 与灯塔色 ${beacon} 只差 ΔE ${deltaE(step, beacon).toFixed(1)}`);
    }
  }
});

test("没有哪个组件偷偷再定义一个涨红或跌绿", () => {
  // 找的是「跟涨/跌很像但不相等」的裸色号：完全相等说明就是同一个值（没问题），
  // 差得远说明是别的意思（也没问题），**只差一点点的才是漏网的复制品**——
  // 简报图的 #d03b3b 当年就是这么活下来的，它跟 --cinnabar 只差 ΔE 4.0。
  //
  // 只比涨和跌。中性灰、纸白这些天生互相接近，拿进来比只会一片红。
  const marketReds = [marketInk.paper.up, marketInk.ink.up] as string[];
  const marketGreens = [marketInk.paper.down, marketInk.ink.down] as string[];
  const allowed = new Set<string>([
    ...marketReds, ...marketGreens,
    ...Object.values(marketRamp).flatMap((set) => Object.values(set).flat() as string[]),
  ]);
  // **只管画市场的那几个组件。**
  //
  // 站内别处也有红有绿——方法体检的好/差、证据的支持/削弱、事件重要度。
  // 它们说的不是涨跌，红绿在中文语境里本来就承载多种意思，一刀切要求它们
  // 也用市场色，只会把「同一个意思一个颜色」变成「同一个颜色好几个意思」，
  // 那是更糟的一头。这里守的是**涨跌这一个意思在市场图上不许有第二份**。
  const components = join(HERE, "..", "components");
  const MARKET_FILES = ["MarketCockpit.tsx", "HeatmapChart.tsx", "BriefingCharts.tsx"];
  const offenders: string[] = [];
  for (const file of readdirSync(components).filter((name) => MARKET_FILES.includes(name))) {
    const source = readFileSync(join(components, file), "utf8");
    for (const [, hex] of source.matchAll(/"(#[0-9a-fA-F]{6})"/g)) {
      const value = hex.toLowerCase();
      if (allowed.has(value)) continue;
      for (const reference of [...marketReds, ...marketGreens]) {
        const distance = deltaE(value, reference);
        if (distance < 8) offenders.push(`${file}: ${value} 与市场色 ${reference} 只差 ΔE ${distance.toFixed(1)}`);
      }
    }
  }
  assert.deepEqual(offenders, [],
    `又出现了第二份涨跌色。改成从 chartTokens 的 marketInk 取：\n  ${offenders.join("\n  ")}`);
});
