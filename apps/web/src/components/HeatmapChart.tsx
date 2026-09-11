import * as echarts from "echarts/core";
import { TooltipComponent, VisualMapComponent } from "echarts/components";
import { TreemapChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import type { HeatmapView } from "../types";
import { chartFont, marketInk, marketRamp, rampColor, tileInk } from "./chartTokens";

echarts.use([TooltipComponent, VisualMapComponent, TreemapChart, CanvasRenderer]);

// 这一页跟首页驾驶舱是**同一张图的两种范围**，穿同一套语言（深海舱），
// 所以取深底那一组。原来它用纸面那组配白卡片，从首页点「打开完整市场云图」
// 进来像换了个网站。真源在 chartTokens。
const SEQUENTIAL = marketRamp.ink.sequential;
const DIVERGING = marketRamp.ink.diverging;
const BEACON = marketInk.ink.beacon;
const WELL = marketInk.ink.ground;

function quantiles(values: number[]): [number, number] {
  if (values.length === 0) return [0, 1];
  const sorted = [...values].sort((first, second) => first - second);
  const at = (fraction: number) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * fraction)))];
  return [at(0.05), at(0.95)];
}

export function HeatmapChart({ view, onDrill }: { view: HeatmapView; onDrill: (tile: { name: string; symbol: string | null }) => void }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const range = useMemo(() => {
    const values = view.tiles.map((tile) => tile.metric_value).filter((value): value is number => value !== null);
    if (view.metric_kind === "diverging") {
      const [low, high] = quantiles(values);
      const bound = Math.max(Math.abs(low), Math.abs(high), 1);
      return [-bound, bound] as [number, number];
    }
    return quantiles(values);
  }, [view]);

  useEffect(() => {
    if (!chartRef.current || view.tiles.length === 0) return;
    // 先取已有实例：StrictMode 下 effect 会跑两遍，同一个 DOM 上 init 两次会留下
    // 一个谁也 dispose 不掉的孤儿实例（已删掉的 MarketMap 当年踩过，这里一直没跟上）。
    const chart = echarts.getInstanceByDom(chartRef.current)
      ?? echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    const unit = view.metric_unit;
    const ramp = view.metric_kind === "diverging" ? DIVERGING : SEQUENTIAL;
    chart.setOption({
      animationDuration: 420,
      aria: { enabled: true, description: `${view.scope_label}市场云图，面积为总市值，颜色为${view.metric_label}` },
      backgroundColor: "transparent",
      tooltip: {
        backgroundColor: "rgba(9, 28, 36, .96)",
        borderColor: "#36545e",
        borderWidth: 1,
        padding: [10, 12],
        textStyle: { color: "#eff7f5", fontSize: 12, lineHeight: 19 },
        confine: true,
        formatter: (params: unknown) => {
          const item = (params as { data?: { name: string; metricValue: number | null; size: number; count: number; symbol: string | null; watched?: Array<{ name: string }> } }).data;
          if (!item) return "";
          const usesCap = view.size_basis === "总市值";
          const cap = usesCap
            ? (item.size >= 1e12 ? `${(item.size / 1e12).toFixed(2)} 万亿` : `${(item.size / 1e8).toFixed(0)} 亿`)
            : `${item.size} 家`;
          const lines = [
            `<strong>${item.name}</strong>${item.symbol ? ` <span style="font-family:${chartFont}">${item.symbol}</span>` : ""}`,
            `${view.metric_label} <strong>${item.metricValue === null ? "缺数据" : `${item.metricValue}${unit}`}</strong>`,
            `${view.size_basis} ${cap}`,
          ];
          if (item.count > 1) lines.push(`${item.count} 家公司的中位数`);
          if (item.watched?.length) {
            lines.push(`<span style="color:${BEACON}">◆ 已建档：${item.watched.map((one) => one.name).join("、")}</span>`);
          }
          return lines.join("<br/>");
        },
      },
      visualMap: {
        type: "continuous",
        min: range[0],
        max: range[1],
        calculable: false,
        show: true,
        orient: "horizontal",
        left: "center",
        bottom: 2,
        itemHeight: 90,
        itemWidth: 9,
        textStyle: { color: "#a8bdc0", fontSize: 9, fontFamily: chartFont },
        formatter: (value: number) => `${value.toFixed(1)}${unit}`,
        inRange: { color: view.metric_kind === "diverging" ? DIVERGING : SEQUENTIAL },
        dimension: 1,
        seriesIndex: 0,
      },
      series: [
        {
          type: "treemap",
          // 可缩放拖动：全 A 五千多块，不能拖就只能看最大的那几十个
          roam: true,
          nodeClick: false,
          breadcrumb: { show: false },
          top: 4,
          right: 4,
          bottom: 34,
          left: 4,
          label: {
            show: true,
            fontFamily: "PingFang SC, Microsoft YaHei, sans-serif",
            formatter: (params: { data?: { name: string; metricValue: number | null; watched?: Array<{ name: string }> } }) => {
              if (!params.data) return "";
              const value = params.data.metricValue;
              const watched = params.data.watched ?? [];
              const beacon = watched.length
                ? `\n{watch|◆ ${watched.slice(0, 2).map((one) => one.name).join(" · ")}${watched.length > 2 ? ` +${watched.length - 2}` : ""}}`
                : "";
              return `{name|${params.data.name}}\n{value|${value === null ? "—" : `${value}${unit}`}}${beacon}`;
            },
          },
          itemStyle: { borderColor: WELL, borderWidth: 2, gapWidth: 2 },
          emphasis: { itemStyle: { borderColor: "#eff7f5", borderWidth: 2 } },
          // **字色跟着格子算。** 原来写死白字，而顺序色阶的浅档是浅蓝灰：
          // 白字压上去只有 1.11 / 1.39 / 1.90 / 2.89:1 —— 数值低的那些格子整片糊掉，
          // 而它们恰恰是这张图上最该看清的一半。
          data: view.tiles.map((tile) => {
            const fill = rampColor(tile.metric_value ?? range[0], range, ramp);
            const ink = tileInk(fill);
            return {
              name: tile.name,
              symbol: tile.symbol,
              value: [tile.size, tile.metric_value ?? range[0]],
              metricValue: tile.metric_value,
              size: tile.size,
              count: tile.count,
              watched: tile.watched,
              itemStyle: {
                color: fill,
                // 金边 = 这个格子里有你建过档的公司。**全站只有这一件事用金。**
                borderColor: tile.watched?.length ? BEACON : WELL,
                borderWidth: tile.watched?.length ? 3 : 2,
              },
              label: {
                color: ink.strong,
                rich: {
                  name: { color: ink.strong, fontSize: 12, fontWeight: 600, lineHeight: 18 },
                  value: { color: ink.soft, fontSize: 10, lineHeight: 15, fontFamily: chartFont },
                  watch: { color: ink.mark, fontSize: 10, fontWeight: 650, lineHeight: 15 },
                },
              },
            };
          }),
        },
      ],
    });
    chart.on("click", (event) => {
      const data = (event as { data?: { name?: string; symbol?: string | null } }).data;
      if (data?.name) onDrill({ name: data.name, symbol: data.symbol ?? null });
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [view, range, onDrill]);

  return <div className="heatmap-chart" ref={chartRef} role="img" aria-label={`${view.scope_label}市场云图`} />;
}
