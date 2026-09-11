import * as echarts from "echarts/core";
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from "echarts/components";
import { LineChart, ScatterChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef, useState } from "react";

import type { PriceBar, ResearchEventRecord } from "../types";
import { chartFont, chartInk, chartPalette, labelPlate, moveColor, signedPercent, tooltipBase } from "./chartTokens";

echarts.use([
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  LineChart,
  ScatterChart,
  CanvasRenderer,
]);

const RANGES = [
  { key: "3m", label: "近 3 月", sessions: 62 },
  { key: "6m", label: "近 6 月", sessions: 122 },
  { key: "1y", label: "近一年", sessions: 244 },
] as const;

type RangeKey = (typeof RANGES)[number]["key"];

const EVENT_COLOR: Record<string, string> = {
  high: chartPalette.cinnabar,
  medium: chartPalette.amber,
  low: chartPalette.slate,
};

const EVENT_LABEL: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

interface EventMarker {
  event: ResearchEventRecord;
  bar: PriceBar;
}

interface PriceTrendProps {
  bars: PriceBar[];
  high52w?: number | null;
  low52w?: number | null;
  events?: ResearchEventRecord[];
}

function movingAverage(values: number[], window: number): (number | null)[] {
  const output: (number | null)[] = [];
  let sum = 0;
  for (let index = 0; index < values.length; index += 1) {
    sum += values[index];
    if (index >= window) sum -= values[index - window];
    output.push(index >= window - 1 ? Number((sum / window).toFixed(2)) : null);
  }
  return output;
}

function currency(value: number): string {
  return `¥ ${value.toFixed(2)}`;
}

export function PriceTrend({ bars, high52w = null, low52w = null, events = [] }: PriceTrendProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const [rangeKey, setRangeKey] = useState<RangeKey>("6m");

  // 只提供数据真正覆盖的窗口，避免出现看起来可选、实际没有日线的区间。
  const maxRangeIndex = useMemo(() => {
    const covering = RANGES.findIndex((range) => range.sessions >= bars.length);
    return covering === -1 ? RANGES.length - 1 : covering;
  }, [bars.length]);
  const activeIndex = Math.min(
    Math.max(
      RANGES.findIndex((range) => range.key === rangeKey),
      0,
    ),
    maxRangeIndex,
  );
  const activeRange = RANGES[activeIndex];

  const view = useMemo(() => {
    const start = Math.max(0, bars.length - activeRange.sessions);
    const closes = bars.map((bar) => bar.close);
    return {
      displayed: bars.slice(start),
      ma20: movingAverage(closes, 20).slice(start),
      ma60: movingAverage(closes, 60).slice(start),
    };
  }, [bars, activeRange.sessions]);

  const markers = useMemo<EventMarker[]>(() => {
    const { displayed } = view;
    if (displayed.length === 0) return [];
    const firstDate = displayed[0].trade_date;
    const lastDate = displayed[displayed.length - 1].trade_date;
    return events
      .map((event) => {
        const day = event.occurred_at.slice(0, 10);
        if (day < firstDate || day > lastDate) return null;
        // 事件可能落在非交易日，标注到其后的第一个交易日。
        const bar = displayed.find((item) => item.trade_date >= day);
        return bar ? { event, bar } : null;
      })
      .filter((item): item is EventMarker => item !== null);
  }, [events, view]);

  const stats = useMemo(() => {
    const { displayed } = view;
    if (displayed.length === 0) return null;
    const first = displayed[0];
    const last = displayed[displayed.length - 1];
    const closes = displayed.map((bar) => bar.close);
    const highest = Math.max(...closes);
    const lowest = Math.min(...closes);
    return {
      first,
      last,
      highest,
      lowest,
      sessions: displayed.length,
      windowChange: first.close === 0 ? null : Number(((last.close / first.close - 1) * 100).toFixed(2)),
      amplitude: lowest === 0 ? null : Number((((highest - lowest) / lowest) * 100).toFixed(2)),
      position:
        high52w !== null && low52w !== null && high52w > low52w
          ? Number((((last.close - low52w) / (high52w - low52w)) * 100).toFixed(0))
          : null,
    };
  }, [view, high52w, low52w]);

  useEffect(() => {
    if (!chartRef.current || view.displayed.length === 0) return;
    const chart = echarts.init(chartRef.current, undefined, {
      renderer: "canvas",
    });
    chart.setOption(buildPriceTrendOption({ ...view, markers, high52w, low52w }));
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [view, markers, high52w, low52w]);

  return (
    <div className="chart-block">
      <div className="chart-toolbar">
        <div className="chart-range-group" role="group" aria-label="选择价格窗口">
          {RANGES.map((range, index) => (
            <button
              key={range.key}
              type="button"
              className={`chart-range${range.key === activeRange.key ? " chart-range--on" : ""}`}
              disabled={index > maxRangeIndex}
              title={index > maxRangeIndex ? "本地日线尚未覆盖该窗口" : undefined}
              onClick={() => setRangeKey(range.key)}
            >
              {range.label}
            </button>
          ))}
        </div>
        <span className="chart-legend-note">图上标注：区间高低点 · 区间均价 · 52 周高低 · MA20/MA60 · 已记录事件</span>
      </div>
      <div className="price-trend" ref={chartRef} role="img" aria-label="前复权日线收盘价走势与标注" />
      {stats && (
        /* **标签在上、数值在下，四格并排。**
           上一版是 `<ul>` 加 `display:flex; flex-wrap:wrap`：四条并成一行，
           中间只有 18px 的空隙，读的人要自己切分「窗口 2026-02-13 → 2026-08-18
           （122 个交易日） 区间涨跌 +54.17% · 振幅 145.1% 52 周区间 …」。
           每一格自己带标签，就不需要靠空隙去猜哪个数属于哪个词。 */
        <dl className="chart-caption">
          <div>
            <dt>窗口</dt>
            <dd><b>{stats.first.trade_date} → {stats.last.trade_date}</b>
              <em>{stats.sessions} 个交易日</em></dd>
          </div>
          <div>
            <dt>区间涨跌</dt>
            <dd>
              <b className={stats.windowChange !== null && stats.windowChange < 0 ? "quote-down" : "quote-up"}>
                {signedPercent(stats.windowChange)}
              </b>
              <em>振幅 {stats.amplitude === null ? "—" : `${stats.amplitude.toFixed(1)}%`}</em>
            </dd>
          </div>
          <div>
            <dt>52 周区间</dt>
            <dd><b>{low52w === null || high52w === null ? "来源未返回" : `${currency(low52w)} — ${currency(high52w)}`}</b>
              {stats.position !== null && <em>当前价位于 {stats.position}% 处</em>}</dd>
          </div>
          <div>
            <dt>事件标注</dt>
            <dd><b>{events.length === 0 ? "无" : `${markers.length} / ${events.length}`}</b>
              <em>{events.length === 0 ? "还没记过事件" : "窗口内已标注"}</em></dd>
          </div>
        </dl>
      )}
    </div>
  );
}

interface PriceOptionInput {
  displayed: PriceBar[];
  ma20: (number | null)[];
  ma60: (number | null)[];
  markers: EventMarker[];
  high52w: number | null;
  low52w: number | null;
}

/** 纯函数：便于在无浏览器环境下渲染同一份配置做检查。 */
export function buildPriceTrendOption({ displayed, ma20, ma60, markers, high52w, low52w }: PriceOptionInput) {
  const axisDates = displayed.map((bar) => bar.trade_date);
  const closes = displayed.map((bar) => bar.close);
  const highest = Math.max(...closes);
  const lowest = Math.min(...closes);
  const span = highest - lowest || Math.max(highest * 0.1, 1);
  // 52 周高低只有落在当前窗口附近时才画线，否则会把价格曲线压扁；数值仍写在图下的说明里。
  const showHigh = high52w !== null && high52w >= lowest && high52w <= highest + span * 0.35;
  const showLow = low52w !== null && low52w <= highest && low52w >= lowest - span * 0.35;
  // 52 周高低的文字放到远离区间高低点的一侧，避免两条标注叠在一起。
  const spread = Math.max(1, closes.length - 1);
  const highLabelSide = closes.indexOf(highest) / spread < 0.4 ? "insideEndTop" : "insideStartTop";
  const lowLabelSide = closes.indexOf(lowest) / spread < 0.4 ? "insideEndBottom" : "insideStartBottom";
  // 极值落在窗口两端时，文字改放到点的内侧，否则会被网格边缘截断。
  const extremeLabelPosition = (index: number, fallback: "top" | "bottom") => {
    const at = index / spread;
    if (at < 0.06) return "right";
    if (at > 0.94) return "left";
    return fallback;
  };
  const rangeLow = showLow ? Math.min(lowest, low52w as number) : lowest;
  const rangeHigh = showHigh ? Math.max(highest, high52w as number) : highest;
  const padding = (rangeHigh - rangeLow || span) * 0.09;

  const markLines: Record<string, unknown>[] = [
    {
      type: "average",
      name: "区间均价",
      lineStyle: { color: chartPalette.slate, type: "dashed", width: 1 },
      label: {
        ...labelPlate,
        position: "insideEndTop",
        color: chartInk.label,
        fontFamily: chartFont,
        fontSize: 8,
        formatter: (params: { value: number }) => `区间均价 ${currency(params.value)}`,
      },
    },
  ];
  if (showHigh) {
    markLines.push({
      yAxis: high52w,
      name: "52 周高",
      lineStyle: {
        color: chartPalette.cinnabar,
        type: "dotted",
        width: 1,
        opacity: 0.7,
      },
      label: {
        ...labelPlate,
        position: highLabelSide,
        color: chartPalette.cinnabar,
        fontFamily: chartFont,
        fontSize: 8,
        formatter: `52 周高 ${currency(high52w as number)}`,
      },
    });
  }
  if (showLow) {
    markLines.push({
      yAxis: low52w,
      name: "52 周低",
      lineStyle: {
        color: chartPalette.jade,
        type: "dotted",
        width: 1,
        opacity: 0.7,
      },
      label: {
        ...labelPlate,
        position: lowLabelSide,
        color: chartPalette.jade,
        fontFamily: chartFont,
        fontSize: 8,
        formatter: `52 周低 ${currency(low52w as number)}`,
      },
    });
  }

  return {
    animationDuration: 350,
    aria: {
      enabled: true,
      description: "前复权日线收盘价走势，含均线、区间高低点与已记录事件标注",
    },
    grid: { top: 42, right: 62, bottom: 26, left: 46 },
    legend: {
      top: 6,
      left: 0,
      itemWidth: 12,
      itemHeight: 6,
      itemGap: 14,
      textStyle: { color: chartInk.label, fontSize: 10 },
      data: ["收盘价", "MA20", "MA60", ...(markers.length > 0 ? ["已记录事件"] : [])],
    },
    tooltip: {
      ...tooltipBase,
      trigger: "axis",
      axisPointer: {
        type: "line",
        lineStyle: { color: chartInk.faint, type: "dashed" },
        label: {
          backgroundColor: chartPalette.blue,
          fontSize: 9,
          fontFamily: chartFont,
        },
      },
      formatter: (params: unknown) => {
        const rows = params as Array<{ seriesName: string; dataIndex: number }>;
        const priceRow = rows.find((row) => row.seriesName === "收盘价");
        if (!priceRow) return "";
        const bar = displayed[priceRow.dataIndex];
        if (!bar) return "";
        const base = displayed[0].close;
        const cumulative = base === 0 ? null : Number(((bar.close / base - 1) * 100).toFixed(2));
        const lines = [
          `<strong style="font-family:${chartFont}">${bar.trade_date}</strong>`,
          `收盘价 <strong style="font-family:${chartFont}">${currency(bar.close)}</strong>` +
            (bar.change_percent === null
              ? ""
              : ` <span style="color:${moveColor(bar.change_percent)}">${signedPercent(bar.change_percent)}</span>`),
          `区间累计 <span style="color:${moveColor(cumulative)}">${signedPercent(cumulative)}</span>`,
          `MA20 ${ma20[priceRow.dataIndex] === null ? "样本不足" : currency(ma20[priceRow.dataIndex] as number)} · MA60 ${
            ma60[priceRow.dataIndex] === null ? "样本不足" : currency(ma60[priceRow.dataIndex] as number)
          }`,
        ];
        const sameDay = markers.filter((marker) => marker.bar.trade_date === bar.trade_date);
        sameDay.forEach((marker) => {
          const color = EVENT_COLOR[marker.event.importance] ?? chartPalette.slate;
          lines.push(
            `<span style="color:${color}">◆</span> ${marker.event.category}（${EVENT_LABEL[marker.event.importance] ?? "中"}）：${marker.event.title}`,
          );
        });
        return lines.join("<br/>");
      },
    },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: axisDates,
      axisLabel: {
        color: chartInk.axis,
        fontSize: 9,
        fontFamily: chartFont,
        interval: Math.max(0, Math.floor(displayed.length / 5) - 1),
        formatter: (value: string) => value.slice(5),
      },
      axisLine: { lineStyle: { color: chartInk.axisLine } },
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      min: Number((rangeLow - padding).toFixed(2)),
      max: Number((rangeHigh + padding).toFixed(2)),
      axisLabel: {
        color: chartInk.axis,
        fontSize: 9,
        fontFamily: chartFont,
        formatter: (value: number) => value.toFixed(1),
      },
      splitLine: { lineStyle: { color: chartInk.grid, type: "dashed" } },
    },
    series: [
      {
        name: "收盘价",
        type: "line",
        data: closes,
        showSymbol: false,
        smooth: false,
        z: 4,
        lineStyle: { color: chartPalette.blue, width: 2 },
        itemStyle: { color: chartPalette.blue },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(49, 92, 121, 0.16)" },
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
          formatter: (params: { value: number }) => currency(params.value),
        },
        markPoint: {
          symbol: "circle",
          symbolSize: 7,
          data: [
            {
              type: "max",
              name: "区间最高",
              itemStyle: {
                color: chartPalette.cinnabar,
                borderColor: "#ffffff",
                borderWidth: 2,
              },
              label: {
                ...labelPlate,
                position: extremeLabelPosition(closes.indexOf(highest), "top"),
                distance: 7,
                color: chartPalette.cinnabar,
                fontFamily: chartFont,
                fontSize: 8,
                formatter: (params: { value: number }) => `区间高 ${currency(params.value)}`,
              },
            },
            {
              type: "min",
              name: "区间最低",
              itemStyle: {
                color: chartPalette.jade,
                borderColor: "#ffffff",
                borderWidth: 2,
              },
              label: {
                ...labelPlate,
                position: extremeLabelPosition(closes.indexOf(lowest), "bottom"),
                distance: 7,
                color: chartPalette.jade,
                fontFamily: chartFont,
                fontSize: 8,
                formatter: (params: { value: number }) => `区间低 ${currency(params.value)}`,
              },
            },
          ],
        },
        markLine: { symbol: ["none", "none"], silent: true, data: markLines },
      },
      {
        name: "MA20",
        type: "line",
        data: ma20,
        showSymbol: false,
        smooth: true,
        connectNulls: false,
        z: 3,
        lineStyle: { color: chartPalette.amber, width: 1.2 },
        itemStyle: { color: chartPalette.amber },
      },
      {
        name: "MA60",
        type: "line",
        data: ma60,
        showSymbol: false,
        smooth: true,
        connectNulls: false,
        z: 3,
        lineStyle: { color: chartPalette.slate, width: 1.2, type: "dashed" },
        itemStyle: { color: chartPalette.slate },
      },
      {
        name: "已记录事件",
        type: "scatter",
        symbol: "diamond",
        symbolSize: 11,
        z: 8,
        data: markers.map((marker) => ({
          value: [marker.bar.trade_date, marker.bar.close],
          itemStyle: {
            color: EVENT_COLOR[marker.event.importance] ?? chartPalette.slate,
            borderColor: "#ffffff",
            borderWidth: 2,
          },
        })),
      },
    ],
  };
}
