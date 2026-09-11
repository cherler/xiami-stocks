/**
 * 钱从哪来、去了哪 —— 一张桑基图。
 *
 * ## 为什么是桑基图而不是又一张饼
 *
 * 饼图回答「构成」，桑基图回答**「流向」**。对一份年报要问的正是流向：
 * 赚到的钱有多少分给了你、多少投回生意里、多少趴在账上。
 *
 * 这些数表格里都有，只是分散在三张报表上，**而且要减一次才看得见**。
 * 减出来那个数恰恰最要紧：2025 年茅台经营现金流 615.2 亿、分红与利息 672.4 亿、
 * 资本开支 31.3 亿 —— 相加**超出 88.5 亿**。表格里要翻两页再减一次；
 * 图上是一根从左边进来的流。
 *
 * ## 倒算出来的那几根要看得出来
 *
 * 「税金与其他」「留在账上」不是报表上的任何一行，是减出来的。它们在图上跟
 * 「营业成本」长得一模一样，所以**画成斜纹、并在提示里写明**——
 * 不标的话，读的人会拿它去核年报，核不到，然后整张图都不敢信了。
 *
 * ## 颜色
 *
 * 不自己定色：全部走 chartInk（跟着深浅外观走）+ 市场色那一套。
 * 唯一的例外是「倒算」用的那个灰，它要的是"这一根不一样"，不是"这一根是坏的"。
 */

import * as echarts from "echarts/core";
import { SankeyChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

import { chartFont, chartInk, tooltipBase } from "./chartTokens";

echarts.use([TooltipComponent, SankeyChart, CanvasRenderer]);

export type MoneyLink = {
  source: string; target: string; value: number; item: string; derived: boolean;
  /** 倒算流量的白话说明。**跟 item 分开**：一句能拿去核年报，一句不能。 */
  explain?: string;
};
export type MoneyBlock = {
  total: number; links: MoneyLink[]; note: string; shortfall?: number;
  /** 左边那层缺了、而且点一下就能补上时是 "syncable"。 */
  left_fix?: string;
};

/** 把 `**粗体**` 渲染出来。三段说明文字共用一个，别各写一遍。 */
function rich(text: string) {
  return text.split("**").map((part, index) =>
    index % 2 === 1 ? <b key={index}>{part}</b> : <span key={index}>{part}</span>);
}

/** 亿元。**只在显示这一层换算** —— 后端一律给元，换过的数再想核回报表得先反算。 */
function yi(value: number): string {
  return `${(value / 1e8).toFixed(1)} 亿`;
}

/**
 * 一行标签大概多宽（像素）。中日韩字符按一个字宽算，其余按 0.55。
 *
 * **要这个数是因为左边那排标签会被裁掉。** 桑基图的左右留白是写死的常数，
 * 而最左一列的名字长短完全取决于这家公司怎么分部：「工业制品及绿色能源 173.8 亿」
 * 有 9 个汉字，在 118px 的留白里被切成「品及绿色能源」—— 一个不认识的词。
 * 裁掉的是开头几个字，所以它甚至不像被裁了，像是数据本来就长这样。
 */
function labelWidth(text: string, fontSize: number): number {
  let units = 0;
  for (const ch of text) units += /[⺀-鿿＀-￯]/.test(ch) ? 1 : 0.55;
  return units * fontSize;
}

// **按角色给色，不按位置。** 参考图里收入侧是冷色、支出侧是暖色、
// 落到自己口袋里的是绿 —— 那不是装饰，是三种性质不同的钱。
const HUE_SOURCE = "#4a8fd4";     // 收入来源（分部）
const HUE_TRUNK = "#1f4f7a";      // 总收入这根主干
const HUE_OUT = "#eb6834";        // 花出去的
const HUE_KEEP = "#277b66";       // 剩下的 / 到股东手上的
const HUE_DERIVED = "#8a94a3";    // 倒算出来的

function colorOf(name: string, derived: boolean, sources: Set<string>): string {
  if (name === "营业总收入") return HUE_TRUNK;
  if (name === "归母净利润" || name === "分红与利息" || name === "留在公司") return HUE_KEEP;
  if (derived) return HUE_DERIVED;
  if (sources.has(name)) return HUE_SOURCE;
  return HUE_OUT;
}

function Sankey({ block, height }: { block: MoneyBlock; height: number }) {
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!box.current) return;
    const chart = echarts.init(box.current, undefined, { renderer: "canvas" });
    const names = new Set<string>();
    for (const link of block.links) { names.add(link.source); names.add(link.target); }
    const derivedNames = new Set(block.links.filter((l) => l.derived).map((l) => l.target));
    // 最左那一列（只出不进）：给它们冷色，并把标签放到左边去。
    const targets = new Set(block.links.map((l) => l.target));
    const sources = new Set(block.links.map((l) => l.source).filter((n) => !targets.has(n)));
    /** 一个节点的吞吐量：进来的优先（末端节点没有进只有出）。 */
    const total = (name: string) => {
      const into = block.links.filter((l) => l.target === name)
        .reduce((sum, l) => sum + l.value, 0);
      return into > 0 ? into : block.links.filter((l) => l.source === name)
        .reduce((sum, l) => sum + l.value, 0);
    };
    // 左边留白按**最左那一列里最长的那个标签**算，不写死。
    //
    // 一版是「有分部就按分部名算，没有就按『营业总收入』算」—— 而最左一列并不只有
    // 这两种住户：亏损期还会多一路「收入不够的部分」，它比营业总收入长两个字，
    // 于是被裁成「入不够的部分」。**别去猜那一列里站着谁，问 sources 就行。**
    // 没有分部时它只有一个节点，留白自然就收窄了，不用另开一个分支。
    const left = Math.min(210, Math.max(96,
      Math.max(...[...sources].map((n) => labelWidth(`${n} ${yi(total(n))}`, 10))) + 14));

    chart.setOption({
      backgroundColor: "transparent",
      textStyle: { fontFamily: chartFont },
      tooltip: {
        ...tooltipBase,
        // **提示里给的是科目原名**，那是这张图能被核对的全部依据。
        formatter: (params: { dataType: string; data: MoneyLink & { name?: string } }) => {
          if (params.dataType !== "edge") return params.data.name ?? "";
          const link = params.data;
          // **口径写在这里，不写在图下面。**
          //
          // 「分红与利息对应的是上一年度的利润」「税金与其他含少数股东损益」这类话
          // 原来堆在图下面成了三行小字（使用者原话：别那么多废话），而它们
          // 只在你看那一根的时候才有用。item 仍然只放科目原名 —— 那是能核年报的
          // 那一句，跟口径说明的可信度完全不同，两行分开写。
          const head = link.derived
            ? "<span style='opacity:.75'>倒算出来的，报表上没有这一行</span>"
            : `<span style='opacity:.75'>${link.item}</span>`;
          const origin = link.explain
            ? `${head}<br/><span style='opacity:.62'>${link.explain}</span>`
            : head;
          return `${link.source} → ${link.target}<br/><b>${yi(link.value)}</b><br/>${origin}`;
        },
      },
      series: [{
        type: "sankey",
        // 左右都要留够：两边各有一排「名字 + 金额」的标签。
        left, right: 150, top: 12, bottom: 12,
        nodeWidth: 14,
        // **不让它自己重排上下次序。**
        //
        // 默认 layoutIterations=32 会跑一轮交叉最小化，把后端排好的次序推翻 ——
        // 净利润那根被挪回费用中间，正是使用者说「极其别扭」的那个样子。
        // 而它的启发式只顾少几条交叉，管不了"哪一根该在最上面"这种语义。
        // 这张图固定三到四列、交叉本来就少，**位置可预测比少一条交叉值钱**：
        // 次序由 money_flow.py 决定，那边解释得清为什么净利润排第一根。
        layoutIterations: 0,
        // **必须是 left，不能用默认的 justify。**
        //
        // justify 会把"只进不出"的节点全部推到最右一列。这张图里 营业成本 /
        // 销售费用 / 税金与其他 都是末端，于是它们跟三列开外的 分红与利息、
        // 留在公司 挤在同一列，而**归母净利润独自留在中间那列** ——
        // 它明明和营业成本是同一层（都是从营业总收入里分出去的），画出来却错开一格。
        // 使用者原话：「看着极其别扭」。left 让每个节点待在自己真实的层数上。
        nodeAlign: "left",
        // **nodeGap 必须小。**
        //
        // 它是同一列节点之间的间距，而两列的节点数不一样：左边 1 个（0 个间隙）、
        // 右边 6 个（5 个间隙）。为了两列都放得下，整张图按「右列 = 数值高度 + 间隙总和」
        // 缩放 —— 间距一大，左边那根就明显比右边一摞矮，看起来是**总数对不上**。
        //
        // 使用者第一眼就是这么读的（截图圈了左边那根）。**版式问题伪装成数据问题
        // 比版式问题本身糟得多**：他会开始怀疑这张图的数。
        // 标签重叠改用「高度按条数给」解决，不靠间距。
        nodeGap: 6,
        emphasis: { focus: "adjacency" },
        data: [...names].map((name) => ({
          name,
          itemStyle: { color: colorOf(name, derivedNames.has(name), sources), borderWidth: 0 },
          // **最左一列的标签放左边。** 都堆在节点右侧的话，它们会压在流量上，
          // 而那正是参考图里最清爽的一块（左边一排、右边一排，中间留给流）。
          ...(sources.has(name) ? { label: { position: "left" as const } } : {}),
        })),
        links: block.links.map((link) => ({
          ...link,
          lineStyle: {
            color: colorOf(link.target, link.derived, sources),
            opacity: link.derived ? 0.22 : 0.38,
            // 倒算的那几根画成斜纹：一眼看得出"这一根跟别的不是一回事"
            ...(link.derived ? { type: "dashed" as const } : {}),
          },
        })),
        label: {
          color: chartInk.label,
          fontSize: 10,
          // **把金额标在名字后面。** 桑基图的粗细只给得出"大概几倍"，
          // 而这一页是拿来核年报的 —— 没有数就没法核。
          formatter: ({ name }: { name: string }) => `${name} ${yi(total(name))}`,
        },
      }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [block]);

  return <div ref={box} style={{ width: "100%", height }} />;
}

export function MoneyFlow({ view, onSyncSegments, syncing }: {
  view: {
    available: boolean; report_date?: string; income: MoneyBlock | null;
    period_label?: string; note?: string; boundary?: string;
  };
  /** 取年报分部附注（补上图的左半边）。**按钮画在这里**，见下面那段。 */
  onSyncSegments?: () => void;
  syncing?: boolean;
}) {
  if (!view.available) {
    return <div className="empty-state">{view.note || "还画不出来。"}</div>;
  }
  // **标题里的期名由后端拼。** 年报、中报、三季报、一季报画出来形状一模一样，
  // 而把三季报当年报读，后面每一个结论都是错的 —— 这四个字是这一页最要紧的一句话，
  // 只该有一处拼它。前端自己 slice 日期的那一版，季报会被写成「2025 年报」。
  const label = view.period_label || String(view.report_date ?? "");
  return <div className="money-flow">
    {view.income && <section className="money-flow-block">
      <h4>钱从哪几门生意进来，一路出去 · {label}</h4>
      <Sankey block={view.income} height={Math.max(300, view.income.links.length * 44)} />
      <p className="chart-note">
        {rich(view.income.note)}
        {/* **能当场补上的缺口，按钮就画在缺口旁边。**
            原来这里写的是一句话：「到『主营构成』点一次同步主营构成」——
            而那块面板在**产业链页签**里，跟这张图隔着一整个页签。使用者的回应是
            「哪里有这个按钮？我就没看到」。一句指路说明再准确，也不如一个按钮：
            让人跨页签去找一个按钮，等于要求所有人在看这张图之前先做一道功课。 */}
        {view.income.left_fix === "syncable" && onSyncSegments && <>
          {" "}
          <button type="button" className="text-button" disabled={syncing}
            onClick={onSyncSegments}>{syncing ? "正在取…" : "取一次分部附注"}</button>
        </>}
      </p>
    </section>}
    {view.boundary && <p className="chart-note money-flow-boundary">{rich(view.boundary)}</p>}
  </div>;
}
