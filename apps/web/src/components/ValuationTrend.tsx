import * as echarts from "echarts/core";
import { GridComponent, MarkAreaComponent, MarkLineComponent, MarkPointComponent, TooltipComponent } from "echarts/components";
import { LineChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef } from "react";

import type { ValuationPoint } from "../types";
import { chartFont, chartInk, chartPalette, labelPlate, tooltipBase } from "./chartTokens";

echarts.use([
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  LineChart,
  CanvasRenderer,
]);

function quantile(sorted: number[], fraction: number): number | null {
  if (sorted.length === 0) return null;
  const position = (sorted.length - 1) * fraction;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

export function ValuationTrend({ points, label }: { points: ValuationPoint[]; label: string }) {
  const chartRef = useRef<HTMLDivElement>(null);
  const bands = useMemo(() => {
    const sorted = points.map((point) => point.value).sort((first, second) => first - second);
    return {
      p25: quantile(sorted, 0.25),
      median: quantile(sorted, 0.5),
      p75: quantile(sorted, 0.75),
    };
  }, [points]);

  useEffect(() => {
    if (!chartRef.current || points.length === 0) return;
    const chart = echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    const values = points.map((point) => point.value);
    const current = values[values.length - 1];
    chart.setOption({
      animationDuration: 350,
      aria: { enabled: true, description: `${label}历史序列，含中位数与 25%–75% 区间` },
      grid: { top: 18, right: 58, bottom: 26, left: 46 },
      tooltip: {
        ...tooltipBase,
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: chartInk.faint, type: "dashed" } },
        formatter: (params: unknown) => {
          const rows = params as Array<{ dataIndex: number }>;
          const point = points[rows[0]?.dataIndex ?? 0];
          if (!point) return "";
          return `<strong style="font-family:${chartFont}">${point.point_date}</strong><br/>${label} <strong>${point.value.toFixed(2)}</strong>`;
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: points.map((point) => point.point_date),
        axisLabel: {
          color: chartInk.axis,
          fontSize: 9,
          fontFamily: chartFont,
          interval: Math.max(0, Math.floor(points.length / 5) - 1),
          formatter: (value: string) => value.slice(0, 7),
        },
        axisLine: { lineStyle: { color: chartInk.axisLine } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        scale: true,
        axisLabel: { color: chartInk.axis, fontSize: 9, fontFamily: chartFont, formatter: (value: number) => value.toFixed(0) },
        splitLine: { lineStyle: { color: chartInk.grid, type: "dashed" } },
      },
      series: [
        {
          name: label,
          type: "line",
          data: values,
          showSymbol: false,
          smooth: false,
          lineStyle: { color: chartPalette.blue, width: 1.6 },
          itemStyle: { color: chartPalette.blue },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: "rgba(49, 92, 121, 0.12)" },
              { offset: 1, color: "rgba(49, 92, 121, 0.01)" },
            ]),
          },
          endLabel: {
            ...labelPlate,
            show: true,
            color: chartPalette.blue,
            fontFamily: chartFont,
            fontSize: 9,
            distance: 6,
            formatter: () => current.toFixed(2),
          },
          markArea:
            bands.p25 !== null && bands.p75 !== null
              ? {
                  silent: true,
                  itemStyle: { color: "rgba(49, 92, 121, 0.06)" },
                  label: {
                    show: true,
                    position: "insideTopLeft",
                    color: chartInk.faint,
                    fontFamily: chartFont,
                    fontSize: 8,
                    formatter: "25%–75% 区间",
                  },
                  data: [[{ yAxis: bands.p25 }, { yAxis: bands.p75 }]],
                }
              : undefined,
          markLine:
            bands.median !== null
              ? {
                  symbol: ["none", "none"],
                  silent: true,
                  data: [
                    {
                      yAxis: bands.median,
                      lineStyle: { color: chartPalette.slate, type: "dashed", width: 1 },
                      label: {
                        ...labelPlate,
                        position: "insideStartTop",
                        color: chartInk.label,
                        fontFamily: chartFont,
                        fontSize: 8,
                        formatter: `中位数 ${bands.median.toFixed(2)}`,
                      },
                    },
                  ],
                }
              : undefined,
        },
      ],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [points, label, bands]);

  return <div className="valuation-trend" ref={chartRef} role="img" aria-label={`${label}历史序列`} />;
}
