/**
 * 这家公司自己这些年怎么走的。
 *
 * ## 为什么重画
 *
 * 原来是**一张双轴五系列图**：营收、净利、现金流（亿元）和负债率、ROE（%）
 * 挤在同一张图上，左右各一根 Y 轴。双轴是最常见的图表错误——两个量纲共用一张图，
 * 读者会不自觉地去比较两条线的高低起伏和交叉点，而那些比较**毫无意义**：
 * ROE 那条线"穿过"营收那条柱，不代表任何事，只取决于两根轴各自怎么缩放。
 *
 * 拆成两张，每张一根轴：
 *
 * - **规模**（亿元）：营收 / 归母净利润 / 经营现金流。同一个单位，同一根轴，
 *   高低直接可比。这样"利润有没有变成现金"是看得见的——两根柱子的差距就是答案，
 *   而这恰好是财报里最该问的一个问题。
 * - **质量**（%）：净利率 / 年报 ROE / 资产负债率。也是同一个单位。
 *
 * ## 只画年报
 *
 * **A 股的财报是累计口径**：一季报是 1–3 月，半年报是 1–6 月，三季报是 1–9 月。
 * 按报告期连线会得到一条每年跌回谷底再爬上去的锯齿——那不是季节性，
 * 是口径造成的假象，而它看起来完全像真的。所以一年一个点。
 *
 * ## 金额画柱、比率画线
 *
 * 柱子表示"这一年有多少"（可加总的量），线表示"这一年是什么水平"（不可加总的率）。
 * 反过来用会让人把比率读成可以累加的东西。
 *
 * ## 颜色
 *
 * #2a78d6 / #eb6834 / #4a3aa7，跑过 validate_palette --mode light 全部 PASS
 * （正常视力最小 ΔE 33.6、色觉障碍 24.7、对比度全过 3:1）。与公司时间轴同一套。
 * 两张图复用同一组颜色但语义不同，所以各自带图例。
 */

import * as echarts from "echarts/core";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { BarChart, LineChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import type { FinancialPeriod } from "../types";
import { chartFont, chartInk, tooltipBase } from "./chartTokens";

echarts.use([GridComponent, LegendComponent, TooltipComponent, BarChart, LineChart, CanvasRenderer]);

const HUES = ["#2a78d6", "#eb6834", "#4a3aa7"] as const;

const SCALE_SERIES = [
  { key: "revenue", label: "营业收入" },
  { key: "net_profit", label: "归母净利润" },
  { key: "operating_cash_flow", label: "经营现金流" },
] as const;

const QUALITY_SERIES = [
  { key: "net_margin", label: "净利率" },
  { key: "roe_estimate", label: "年报 ROE" },
  { key: "debt_ratio", label: "资产负债率" },
] as const;

/** 按列名取值。FinancialPeriod 没有索引签名，直接下标会被类型系统挡住。 */
function field(period: FinancialPeriod, key: string): unknown {
  return (period as unknown as Record<string, unknown>)[key];
}

function toYi(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  return Math.round((Number(value) / 1e8) * 100) / 100;
}

function asPercent(value: unknown): number | null {
  return value === null || value === undefined ? null : Number(value);
}

function Panel({ title, unit, years, series, kind }: {
  title: string; unit: string; years: string[]; kind: "amount" | "ratio";
  series: { label: string; values: (number | null)[] }[];
}) {
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!boxRef.current) return;
    const chart = echarts.init(boxRef.current, undefined, { renderer: "canvas" });
    chart.setOption({
      animation: false,
      grid: { left: 48, right: 14, top: 34, bottom: 24 },
      legend: {
        top: 2, left: 0, itemWidth: 10, itemHeight: 10, itemGap: 14,
        textStyle: { color: chartInk.label, fontSize: 10, fontFamily: chartFont },
      },
      tooltip: {
        ...tooltipBase, trigger: "axis",
        axisPointer: { type: kind === "amount" ? "shadow" : "line" },
        formatter: (points: any[]) =>
          `${points[0].axisValue} 年报<br/>` + points.map((p) =>
            `${p.marker}${p.seriesName} <b>${p.value ?? "—"}</b> ${unit}`).join("<br/>"),
      },
      xAxis: {
        type: "category", data: years, boundaryGap: kind === "amount",
        axisLine: { lineStyle: { color: chartInk.axisLine } },
        axisTick: { show: false },
        axisLabel: { color: chartInk.label, fontSize: 10, fontFamily: chartFont },
      },
      yAxis: {
        type: "value",
        // 柱子必须以 0 为基准，长度才等于数值；亏损或现金流为负时向下延伸
        min: kind === "amount" ? (v: { min: number }) => (v.min >= 0 ? 0 : v.min) : undefined,
        scale: kind === "ratio",
        axisLine: { show: false }, axisTick: { show: false },
        axisLabel: {
          color: chartInk.label, fontSize: 10, fontFamily: chartFont,
          formatter: (value: number) => (kind === "ratio" ? `${value}%` : `${value}`),
        },
        splitLine: { lineStyle: { color: chartInk.grid, type: "dashed" } },
      },
      series: series.map((s, index) => kind === "amount"
        ? {
            name: s.label, type: "bar", data: s.values, barMaxWidth: 18, barGap: "12%",
            // 圆角只给数据端，底边贴着基线
            itemStyle: { color: HUES[index], borderRadius: [3, 3, 0, 0] },
          }
        : {
            name: s.label, type: "line", data: s.values, smooth: false, connectNulls: false,
            lineStyle: { color: HUES[index], width: 2 },
            itemStyle: { color: HUES[index], borderColor: chartInk.surface, borderWidth: 2 },
            symbolSize: 8,
          }),
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [years, series, kind, unit]);

  return (
    <figure className="growth-panel">
      <figcaption>{title}<span>{unit}</span></figcaption>
      <div ref={boxRef} className="growth-canvas" />
    </figure>
  );
}

export function GrowthChart({ periods }: { periods: FinancialPeriod[] }) {
  const annual = useMemo(
    () => periods.filter((p) => String(p.report_date).slice(5) === "12-31")
                 .sort((a, b) => String(a.report_date).localeCompare(String(b.report_date)))
                 .slice(-10),
    [periods]);

  const years = useMemo(() => annual.map((p) => String(p.report_date).slice(0, 4)), [annual]);
  const scale = useMemo(() => SCALE_SERIES.map((s) => ({
    label: s.label, values: annual.map((p) => toYi(field(p, s.key))),
  })), [annual]);
  const quality = useMemo(() => QUALITY_SERIES.map((s) => ({
    label: s.label, values: annual.map((p) => asPercent(field(p, s.key))),
  })), [annual]);

  if (annual.length < 2) {
    return <div className="empty-state">
      年报期数不足两期，走势画不出来。点右上角「更新财务数据」多同步几年。
    </div>;
  }

  return <>
    <div className="growth-grid">
      <Panel title="规模" unit="亿元" years={years} series={scale} kind="amount" />
      <Panel title="质量" unit="%" years={years} series={quality} kind="ratio" />
    </div>
    <p className="chart-note">
      {years[0]}–{years[years.length - 1]} 共 {annual.length} 期年报。
      <strong>只取年报</strong>：A 股季报是累计口径，混进来会画出一条假的锯齿。三根柱同一根轴，差距就是「利润有没有变成钱」。
    </p>
  </>;
}
