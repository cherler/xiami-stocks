/**
 * 图表统一视觉口径。颜色沿用研究台的纸墨色系，
 * 并按“同一实体固定同一颜色”的规则分配，不随筛选变化。
 */
/**
 * 图表墨色。**每次取值都现读 CSS 令牌，不是常量。**
 *
 * canvas 读不到 CSS 变量，所以这里一直是把纸面色系抄了一份 —— 而抄的那份
 * 没有深色档，全仓图表组件里也没有任何一处读主题（没有 data-theme、
 * 没有 getComputedStyle、没有媒体查询）。2026-08-16 拿真账号登进去看：
 * 深色下一张 2 年市盈率图上横贯着十几条 **#e7eeee 的亮白虚线**。
 *
 * darkscan 扫不到这个 —— 那个扫描器量的是 DOM 元素的计算样式，
 * **canvas 里的像素它看不见**。这类盲区只能靠真的看一眼。
 *
 * 做成 getter 而不是改成函数，是为了**不动五个组件的任何一行调用**：
 * ECharts 在拼 option 时读属性，那一刻拿到的就是当前外观的值。
 * 兜底值就是原来那一份，CSS 没加载完时行为跟从前一样。
 *
 * ⚠️ 已经画出来的图不会因为切换外观自动重画（组件没重渲染就不会重新拼 option）。
 *    翻一页就正常。要做到即时跟随得给图表挂主题监听，那是另一件事。
 */
function cssInk(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export const chartInk = {
  get axis() { return cssInk("--chart-axis", "#778891"); },
  get label() { return cssInk("--chart-label", "#67797f"); },
  get strong() { return cssInk("--chart-strong", "#2c434d"); },
  get faint() { return cssInk("--chart-faint", "#9aa9ae"); },
  get grid() { return cssInk("--chart-grid", "#e7eeee"); },
  get axisLine() { return cssInk("--chart-axis-line", "#d7e1e2"); },
  get surface() { return cssInk("--chart-surface", "#ffffff"); },
};

/**
 * 市场色：涨、跌、平、灯塔。**全站只有这一份。**
 *
 * ## 为什么单独拎出来
 *
 * 「涨」这一个意思，本仓一度有五个红：styles.css 的 `--cinnabar` #bd493a、
 * 本文件的 #b0402f、简报图的 #d03b3b、驾驶舱的 #ee6a52、云图色阶末端的 #bd493a。
 * 「跌」有五个绿。测下来是两种失败叠在一起：
 *
 *   - #bd493a 与 #b0402f 差 ΔE 3.4，#277b66 与 #2f7f68 差 ΔE 1.4
 *     —— **看不出差别，却要改三个地方**，纯粹的重复；
 *   - #bd493a 与驾驶舱的 #ee6a52 差 ΔE 12.3
 *     —— **同一个意思，翻一页就换个红**，这才是「设计语言不一致」被看见的样子。
 *
 * ## 为什么有两套而不是一套
 *
 * 驾驶舱是深底（#102a35），研究台是纸面。同一个 #bd493a 压在深底上只有 2.1:1，
 * 是看不清的。所以按**底色**分两组，但两组同相：深底那组就是纸面那组保持色相、
 * 抬到 L\*66 的结果（红 30°、绿 173°，两组一致）。这样它们是同一个颜色的两个
 * 明度版本，而不是两个颜色。改的时候改色相，两边一起跟。
 *
 * ## flat 为什么是浅灰而不是中灰
 *
 * 涨跌红绿在**色觉障碍**下靠的只剩明度（红绿轴塌掉）。所以「平」不能选一个跟
 * 红绿一样亮的中灰——原来驾驶舱用 #70858d，它跟跌色在红色盲下只差 ΔE 4.3，
 * 而涨/平/跌三段是**贴在一起的**（市场脉搏那个圆环、简报的涨跌条）。
 * 现在两组的 flat 都用明度拉开：三对两两 ΔE 都在 8 以上（实测最差 10.6）。
 */
export const marketInk = {
  /** 纸面（研究台、市场云图页）。与 styles.css 的 --cinnabar / --jade / --amber 是同一批值。 */
  paper: {
    up: "#bd493a",
    down: "#277b66",
    flat: "#c9ced2",
    beacon: "#b77b2d",
    ground: "#ffffff",
  },
  /** 深底（首页驾驶舱）。保持色相抬到 L*66：红 30°、绿 173°，与上面一组同相。 */
  ink: {
    up: "#dd6857",
    down: "#2aa78a",
    flat: "#b3bec1",
    beacon: "#f2c86f",
    ground: "#102a35",  // = --deck-bg，也是侧栏的色。云图格子之间的缝用它。
  },
} as const;

/**
 * 云图色阶。两条规矩，缺一条图就会骗人：
 *
 * 1. **分歧色阶的中点必须是中性的**，不能是第三个色相。驾驶舱原来的中点是
 *    #294750（蓝青，C=3.9 且偏蓝），于是从 -0.5% 走到 0% 时颜色由绿转**蓝**——
 *    蓝在这张图上不表示任何东西，读者只会把它当成第三类。
 * 2. **明度要单调。** 原来那条是 L\*68 → 38 → 53：走到中点亮度掉 30 点再回升，
 *    人眼把亮度读成强度，于是 -0.1% 看起来比 -1.3% 还极端。
 *
 * 现在两条都是等距的（相邻档 ΔE 11–15），中点近中性（C≈1.2），
 * 明度对称成 V 形；顺序色阶末档也不再撞灯塔金（原来 ΔE 0.6，等于同一个色）。
 */
export const marketRamp = {
  paper: {
    diverging: ["#277b66", "#76a596", "#cad5d7", "#c29088", "#bd493a"],
    sequential: ["#d1e1eb", "#a6bfcd", "#7d9eb1", "#537c93", "#285b76"],
  },
  ink: {
    diverging: ["#2aa78a", "#14836a", "#465153", "#a75549", "#dd6857"],
    sequential: ["#213e3d", "#315e5d", "#3d7c7a", "#50a2a0", "#64c9c6"],
  },
} as const;

/**
 * 色块上该压什么颜色的字——**按色块本身算，不写死。**
 *
 * 写死白字是这两张云图上最实在的一个 bug：市场云图页的顺序色阶前四档是浅蓝灰，
 * 白字压上去只有 1.11 / 1.39 / 1.90 / 2.89:1，**四档里没有一档读得了**；
 * 驾驶舱那条则是两个端点（涨得最多、跌得最多的行业）读不了。
 * 而这两处恰恰是最该被看清的格子。
 *
 * 交给函数算之后，以后换色阶也不会再把这个坑挖回来。
 */
export function tileInk(background: string): { strong: string; soft: string; mark: string } {
  const byte = (start: number) => parseInt(background.slice(start, start + 2), 16);
  const channel = (start: number) => {
    const value = byte(start) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  const luminance = 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
  // 分界取 0.188：这是白字与深字对比度相等的那一点。**这里也是整条色阶最难读的地方**——
  // 底色是中等亮度时，任何一种字都撑不出高对比：换成纯黑最多也只有 4.46:1。
  // 所以这里不吹「全程 AA」，只说实测的地板：四条色阶全程主文字 ≥ 4.17:1、次文字 ≥ 3.3:1。
  // 起点是 1.11:1（六档里四档读不了），这一步是把读不了的变成读得吃力的那一档。
  const strong = luminance > 0.188 ? "#0a161b" : "#f4faf8";
  // 次级文字（那个百分数）**不靠淡颜色拉开层级，靠字号和字重**。
  // 中等亮度的底色对任何一种字都撑不出多少对比度，再把字调淡就直接读不了了——
  // 原来那两个固定值（#3c5057 / #c9d8d9）在色阶中段正好落进这个坑。
  // 这里只往底色方向让 18%，够看出主次，又不会掉到 3:1 以下。
  const soften = (start: number) =>
    Math.round(parseInt(strong.slice(start, start + 2), 16) * 0.82 + byte(start) * 0.18)
      .toString(16)
      .padStart(2, "0");
  return {
    strong,
    soft: `#${soften(1)}${soften(3)}${soften(5)}`,
    // 「已建档」不用金字来说——那一格本来就有一圈金色描边和一个 ◆，
    // 而金字压在中段色块上只有 2.7:1。身份由边框带，文字只管读得清。
    mark: strong,
  };
}

/**
 * 数值 → 色阶上的颜色。**自己算，不交给 visualMap。**
 *
 * 因为字色要跟着块的颜色走（见上面 tileInk），而 visualMap 是在渲染时才把
 * 颜色贴上去的，那时候已经没机会决定这块该压白字还是深字了。
 * 插值放在 sRGB 空间，跟 visualMap 的做法一致——换过来观感不变。
 */
export function rampColor(value: number, range: readonly [number, number], ramp: readonly string[]): string {
  const [min, max] = range;
  const span = max - min || 1;
  const position = Math.max(0, Math.min(1, (value - min) / span)) * (ramp.length - 1);
  const index = Math.min(ramp.length - 2, Math.floor(position));
  const fraction = position - index;
  const at = (hex: string, start: number) => parseInt(hex.slice(start, start + 2), 16);
  const mix = (start: number) =>
    Math.round(at(ramp[index], start) + (at(ramp[index + 1], start) - at(ramp[index], start)) * fraction)
      .toString(16)
      .padStart(2, "0");
  return `#${mix(1)}${mix(3)}${mix(5)}`;
}

/**
 * 图表分类色。**刻意不跟品牌青绿走。**
 *
 * 品牌色的职责是"让人认出这是虾米伙伴"，分类色的职责是"让人区分开这是哪一条"。
 * 把 blue 换成品牌的 #0c9488，它和 jade 就成了两个挨着的青绿，
 * 色觉障碍者几乎分不开——为了品牌一致牺牲掉图表的可读性，本末倒置。
 * 品牌色在图表里出现在别处：强调标注、选中态、坐标轴强调。
 */
export const chartPalette = {
  blue: "#315c79",
  blueSoft: "#8caeb9",
  amber: "#c98a24",
  slate: "#9aabb1",
  // 涨跌不再在这里各写一份 —— 它们跟 .quote-up / .quote-down 是同一个意思，
  // 分开写就是分开漂移（实测已经漂到 ΔE 3.4 / 1.4，看不出差别却要改两处）。
  cinnabar: marketInk.paper.up,
  jade: marketInk.paper.down,
};

export const chartFont = "SFMono-Regular, Consolas, 'Liberation Mono', monospace";

/** 提示框。**这里也必须是 getter。**
 *
 * 原来是个模块级的对象字面量，`chartInk.surface` 在 **import 那一刻**就被求值了 ——
 * 于是上面那套 getter 对它完全无效，提示框永远是纸面白。
 * 一个对象字面量里读另一个对象的 getter，读到的是"那一刻"的值，不是"用的时候"的值。 */
export const tooltipBase = {
  get backgroundColor() { return chartInk.surface; },
  get borderColor() { return chartInk.axisLine; },
  borderWidth: 1,
  padding: [9, 11] as [number, number],
  get textStyle() { return { color: chartInk.strong, fontSize: 10, lineHeight: 17 }; },
  extraCssText: "box-shadow: 0 6px 18px rgba(22, 38, 48, 0.12); border-radius: 2px;",
  confine: true,
};

/** 标注文字压在曲线上时的衬底，保证叠加处仍可读。同理要跟着外观走：
 *  深色下压一块近白的板子，等于在图上贴了张纸。 */
export const labelPlate = {
  get backgroundColor() { return cssInk("--chart-plate", "rgba(248, 250, 249, 0.88)"); },
  padding: [1, 3] as [number, number],
  borderRadius: 2,
};

export function signedPercent(value: number | null, digits = 2): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

/** A 股惯例：红涨绿跌。这里只描述事实方向，不表示买卖倾向。 */
export function moveColor(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value === 0) return chartInk.label;
  return value > 0 ? chartPalette.cinnabar : chartPalette.jade;
}
