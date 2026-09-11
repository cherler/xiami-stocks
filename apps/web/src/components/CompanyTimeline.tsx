/**
 * 公司时间轴：把散在四个页签里的东西放到同一根轴上。
 *
 * **这是列表在结构上做不到的事：对齐。** 估值分位在「行情与估值」、公告在「事件记录」、
 * 交易在「持仓与交易」、投资逻辑在「逻辑与证据」——四个页签来回切，就是没法回答
 * 「我买的时候 PE 在哪、之后出了哪几条实质公告、写下判断之后事实往哪走」。
 *
 * ## 为什么是单轴
 *
 * 估值走势是唯一有连续数值的东西，它占 Y 轴。公告、财报、交易、判断都是**时点**，
 * 不是数量——它们画成轴上的标记，而不是第二条 Y 轴上的线。
 * 双轴是最常见的图表错误：两个不同量纲的东西共用一张图，读者会去比较它们的
 * 高低起伏，而那个比较毫无意义。
 *
 * ## 颜色
 *
 * 三色取自校验过的分类色板（蓝 #2a78d6 估值线、橙 #eb6834 实质公告、
 * 紫 #4a3aa7 我的动作），跑过 validate_palette：正常视力最小 ΔE 33.6、
 * 色觉障碍最小 24.7，对比度全部过 3:1。
 *
 * 没有沿用 chartTokens 里的 jade/blue —— 那两个实测正常视力下 ΔE 只有 12.2，
 * 低于 15 的硬门槛，两条线挨在一起分不出来。
 */

import * as echarts from "echarts/core";
import { GridComponent, MarkLineComponent, MarkPointComponent, TooltipComponent } from "echarts/components";
import { LineChart, ScatterChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import { chartFont, chartInk, tooltipBase } from "./chartTokens";

echarts.use([GridComponent, MarkLineComponent, MarkPointComponent, TooltipComponent,
             LineChart, ScatterChart, CanvasRenderer]);

// 跑过 validate_palette.js --mode light：全部 PASS。改之前请重跑。
const LINE = "#2a78d6";      // 估值分位
const EVENT = "#eb6834";     // 实质公告
const MINE = "#4a3aa7";      // 我的买卖与写下的判断

export type TimelinePayload = {
  company_name: string;
  symbol: string;
  since: string;
  valuation: { date: string; value: number }[];
  events: { date: string; title: string; category: string; relevance: string; handled: boolean }[];
  reports: { date: string; revenue: number | null; net_profit: number | null }[];
  trades: { date: string; side: string; shares: number | null; price: number | null;
            weight_percent: number | null; rationale: string }[];
  theses: { id: number; claim: string; status: string; date: string }[];
  boundary: string;
};

/** 把一个日期落到估值序列上，取那天（或之前最近一天）的值——标记要贴着线走。 */
function valueAt(series: { date: string; value: number }[], when: string): number | null {
  let hit: number | null = null;
  for (const point of series) {
    if (point.date > when) break;
    hit = point.value;
  }
  return hit;
}

/** 把轴上给的值和标记里存的值都归成 "YYYY-MM-DD"。
 *  时间轴的 axisValue 是时间戳，而标记里存的是日期字符串——不归一就永远对不上。 */
function dayKey(value: unknown): string {
  if (typeof value === "string") return value.slice(0, 10);
  const stamp = new Date(value as number);
  return Number.isNaN(stamp.getTime()) ? String(value) : stamp.toISOString().slice(0, 10);
}

export function CompanyTimeline({ data }: { data: TimelinePayload }) {
  const boxRef = useRef<HTMLDivElement>(null);

  const marks = useMemo(() => {
    const line = data.valuation;
    if (line.length === 0) return { events: [], mine: [] };

    // **同一天的公告聚成一个点。** 年报季一天能出九条（审计报告、专项说明、
    // 英文版…全是年报的配套文件）——画九个重叠的圆毫无意义，只会糊成一坨，
    // 还把旁边真正独立的事件盖住。聚合后点的大小反映条数，悬停展开全部标题。
    const byDay = new Map<string, typeof data.events>();
    for (const e of data.events) {
      const bucket = byDay.get(e.date) ?? [];
      bucket.push(e);
      byDay.set(e.date, bucket);
    }

    // 公告贴着估值线画：这样「出这条公告的时候估值在哪」是看得见的，
    // 而不是让人在两个高度之间自己对时间。
    const events = [...byDay.entries()].map(([day, list]) => {
      const anyHigh = list.some((e) => e.relevance === "高");
      const anyOpen = list.some((e) => !e.handled);
      return {
        value: [day, valueAt(line, day) ?? line[line.length - 1].value],
        // 一条 9px、两条 11px、五条以上 15px 封顶——再大就会盖住估值线本身
        symbolSize: Math.min(15, (anyHigh ? 9 : 7) + Math.min(list.length - 1, 3) * 2),
        itemStyle: {
          color: anyOpen ? chartInk.surface : EVENT,
          borderColor: EVENT,
          borderWidth: 2,        // 有未核验的就画成空心：一眼看出还欠着
        },
        meta: { day, list, anyOpen },
      };
    });

    const mine = [
      ...data.trades.map((t) => ({
        value: [t.date, valueAt(line, t.date) ?? line[line.length - 1].value],
        symbolSize: 13,
        itemStyle: { color: MINE, borderColor: chartInk.surface, borderWidth: 2 },
        meta: { kind: "交易", text: `${t.side}${t.weight_percent ? ` ${t.weight_percent}%` : ""}`,
                detail: t.rationale },
      })),
      ...data.theses.map((t) => ({
        value: [t.date, valueAt(line, t.date) ?? line[line.length - 1].value],
        symbolSize: 13,
        itemStyle: { color: chartInk.surface, borderColor: MINE, borderWidth: 2 },
        meta: { kind: "写下判断", text: t.claim, detail: `状态：${t.status}` },
      })),
    ];
    return { events, mine };
  }, [data]);

  useEffect(() => {
    if (!boxRef.current || data.valuation.length === 0) return;
    const chart = echarts.init(boxRef.current, undefined, { renderer: "canvas" });

    chart.setOption({
      animation: false,
      grid: { left: 44, right: 16, top: 18, bottom: 26 },
      tooltip: {
        ...tooltipBase,
        // **整条轴都能问，不是只有点上能问。**
        //
        // 原来是 trigger: "item"：鼠标必须精确压在那个橙点上才有反应，
        // 而点只画在「有公告的那几天」。于是这张图有五百多个交易日，
        // 其中五百天是问不出话来的——看图的人会以为这图只是个装饰。
        //
        // 换成 axis 之后，任何一天都答得出「那天 PE 多少」，
        // 有事的那天再多答几句。事件的详情一个字没少。
        trigger: "axis",
        axisPointer: {
          type: "line",
          snap: true,
          lineStyle: { color: chartInk.faint, type: "dashed" },
          label: { backgroundColor: LINE, fontSize: 9, fontFamily: chartFont },
        },
        formatter: (params: any) => {
          const rows: any[] = Array.isArray(params) ? params : [params];
          const priceRow = rows.find((row) => row.seriesName === "市盈率 TTM") ?? rows[0];
          if (!priceRow) return "";
          const day = dayKey(priceRow.value?.[0] ?? priceRow.axisValue);
          const pe = Number(priceRow.value?.[1]);
          const lines = [
            `<strong style="font-family:${chartFont}">${day}</strong>`,
            `市盈率 TTM <strong style="font-family:${chartFont}">${Number.isFinite(pe) ? pe.toFixed(2) : "—"}</strong>`,
          ];
          // 那一天有没有事——从原始标记里按日子找，不依赖鼠标压中哪个点
          const hitEvent = marks.events.find((item: any) => dayKey(item.value[0]) === day);
          if (hitEvent) {
            const meta: any = hitEvent.meta;
            lines.push(`<b>${meta.list.length} 条实质公告</b>${meta.anyOpen ? " · 有未核验" : ""}`);
            // 最多列五条：年报季一天九条，全列出来 tooltip 会长过屏幕
            lines.push(...meta.list.slice(0, 5).map((e: any) => `${e.relevance === "高" ? "●" : "○"} ${e.title.slice(0, 30)}`));
            if (meta.list.length > 5) lines.push(`<span style="color:${chartInk.label}">…还有 ${meta.list.length - 5} 条</span>`);
          }
          for (const item of marks.mine as any[]) {
            if (dayKey(item.value[0]) !== day) continue;
            lines.push(`<b>${item.meta.kind}</b> ${item.meta.text}`);
            if (item.meta.detail) lines.push(`<span style="color:${chartInk.label}">${item.meta.detail}</span>`);
          }
          return lines.join("<br/>");
        },
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: chartInk.axisLine } },
        axisLabel: { color: chartInk.label, fontSize: 10, fontFamily: chartFont },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        name: "市盈率 TTM",
        nameTextStyle: { color: chartInk.label, fontSize: 10, align: "left" },
        scale: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: chartInk.label, fontSize: 10, fontFamily: chartFont },
        splitLine: { lineStyle: { color: chartInk.grid, type: "dashed" } },
      },
      series: [
        {
          name: "市盈率 TTM",
          type: "line",
          data: data.valuation.map((p) => [p.date, p.value]),
          showSymbol: false,
          lineStyle: { color: LINE, width: 2 },
          z: 1,
          // 财报期画成竖线：它是「数字被更新的时点」，估值的台阶多半在这里
          markLine: {
            silent: true,
            symbol: "none",
            label: { show: false },
            lineStyle: { color: chartInk.axisLine, width: 1, type: "dashed" },
            data: data.reports.map((r) => ({ xAxis: r.date })),
          },
        },
        { name: "实质公告", type: "scatter", data: marks.events, z: 3, symbol: "circle" },
        { name: "我的动作", type: "scatter", data: marks.mine, z: 4, symbol: "diamond" },
      ],
    });

    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [data, marks]);

  if (data.valuation.length === 0) {
    return <div className="empty-state">还没有估值序列。在「行情与估值」页同步一次，这根轴才有底。</div>;
  }

  return <>
    <div ref={boxRef} className="timeline-chart" />
    {/* 图例始终在：光靠颜色区分身份是不够的，色觉障碍与打印都会失效 */}
    <div className="timeline-legend">
      <span><i style={{ background: LINE }} />市盈率 TTM</span>
      <span><i style={{ background: EVENT }} />实质公告（点越大当天越多，空心 = 有未核验）</span>
      <span><i style={{ background: MINE }} />我的买卖与判断</span>
      <span><i className="dash" />财报期</span>
    </div>
  </>;
}
