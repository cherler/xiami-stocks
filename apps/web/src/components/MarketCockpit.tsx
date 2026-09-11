import * as echarts from "echarts/core";
import { GridComponent, TooltipComponent } from "echarts/components";
import { BarChart, LineChart, TreemapChart } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getHeatmap, getMarketFundFlow, getMarketLensStatuses } from "../api";
import type { DashboardSummary, HeatmapTile, HeatmapView, MarketFundFlowView, MarketLensStatus, WatchlistItem } from "../types";
import { marketInk, marketRamp, rampColor, tileInk } from "./chartTokens";

echarts.use([GridComponent, TooltipComponent, BarChart, LineChart, TreemapChart, CanvasRenderer]);

// 驾驶舱是深底，取深底那一组。它跟纸面那组同相，只是抬亮——见 chartTokens 里的说明。
const { up: UP, down: DOWN, flat: FLAT, beacon: BEACON } = marketInk.ink;
const DIVERGING = marketRamp.ink.diverging;
const SEQUENTIAL = marketRamp.ink.sequential;
// 资金流的四个单子档位：借同一支顺序色阶，最亮 = 超大单。跳过最暗那一档，
// 它跟驾驶舱底色只差 ΔE 7，柱子会看不见。
const ORDER_SIZES = [SEQUENTIAL[4], SEQUENTIAL[3], SEQUENTIAL[2], SEQUENTIAL[1]];

type Lens = {
  metric: string;
  label: string;
  group: "表现" | "市场" | "资金";
};

const LENSES: Lens[] = [
  { metric: "change_percent", label: "今日", group: "表现" },
  { metric: "change_5d", label: "5 日", group: "表现" },
  { metric: "change_20d", label: "20 日", group: "表现" },
  { metric: "ytd_change", label: "年内", group: "表现" },
  { metric: "turnover_rate", label: "交易热度", group: "市场" },
  { metric: "abs_change", label: "波动", group: "市场" },
  { metric: "attention_index", label: "市场关注", group: "市场" },
  { metric: "capital_flow", label: "资金流", group: "资金" },
];
const GUARDED_LENSES = new Set(["change_5d", "change_20d", "ytd_change"]);

export type CockpitAction = {
  label: string;
  count: number;
  tone: string;
  onClick: () => void;
};

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function median(values: Array<number | null | undefined>): number | null {
  const items = values.filter(finite).sort((a, b) => a - b);
  if (items.length === 0) return null;
  const middle = Math.floor(items.length / 2);
  return items.length % 2 ? items[middle] : (items[middle - 1] + items[middle]) / 2;
}

function quantileRange(values: number[], diverging: boolean): [number, number] {
  if (values.length === 0) return [0, 1];
  const sorted = [...values].sort((a, b) => a - b);
  const at = (part: number) => sorted[Math.max(0, Math.min(sorted.length - 1, Math.round((sorted.length - 1) * part)))];
  if (diverging) {
    const span = Math.max(Math.abs(at(0.06)), Math.abs(at(0.94)), 0.1);
    return [-span, span];
  }
  const low = at(0.04);
  const high = at(0.96);
  return low === high ? [low, low + 1] : [low, high];
}

function compactCap(value: number): string {
  if (!finite(value)) return "—";
  if (value >= 1e12) return `${(value / 1e12).toFixed(1)} 万亿`;
  if (value >= 1e8) return `${Math.round(value / 1e8)} 亿`;
  return value.toLocaleString("zh-CN");
}

function flowText(value: number | null | undefined, signed = true): string {
  if (!finite(value)) return "—";
  const inYi = value / 1e8;
  const prefix = signed && inYi > 0 ? "+" : "";
  return `${prefix}${inYi.toFixed(Math.abs(inYi) >= 100 ? 0 : 1)} 亿`;
}

function flowTone(value: number | null | undefined): string {
  return !finite(value) || value === 0 ? "" : value > 0 ? "quote-up" : "quote-down";
}

function CapitalFlowChart({ view }: { view: MarketFundFlowView }) {
  const boxRef = useRef<HTMLDivElement>(null);
  const points = useMemo(() => view.points.slice(-30), [view.points]);

  useEffect(() => {
    if (!boxRef.current || points.length === 0) return;
    const chart = echarts.getInstanceByDom(boxRef.current)
      ?? echarts.init(boxRef.current, undefined, { renderer: "canvas" });
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const toYi = (value: number | null) => finite(value) ? value / 1e8 : null;
    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: reduceMotion ? 0 : 360,
      aria: {
        enabled: true,
        description: "全 A 最近三十个交易日资金流动图。柱形分别表示超大单、大单、中单和小单净流入，金色折线表示主力净流入。",
      },
      grid: { top: 28, right: 16, bottom: 34, left: 52 },
      tooltip: {
        trigger: "axis",
        backgroundColor: "rgba(9, 28, 36, .96)",
        borderColor: "#36545e",
        borderWidth: 1,
        padding: [10, 12],
        textStyle: { color: "#eff7f5", fontSize: 12, lineHeight: 19 },
        formatter: (items: unknown) => {
          const rows = items as Array<{ axisValue?: string; marker?: string; seriesName?: string; value?: number | null }>;
          return [`<strong>${rows[0]?.axisValue ?? ""}</strong>`, ...rows.map((item) => `${item.marker ?? ""}${item.seriesName} <strong>${finite(item.value) ? `${item.value > 0 ? "+" : ""}${item.value.toFixed(1)} 亿` : "—"}</strong>`)].join("<br/>");
        },
      },
      xAxis: {
        type: "category",
        data: points.map((point) => point.date.slice(5)),
        axisLine: { lineStyle: { color: "rgba(181, 207, 205, .2)" } },
        axisTick: { show: false },
        axisLabel: { color: "#82999e", fontSize: 10, interval: 4 },
      },
      yAxis: {
        type: "value",
        name: "亿元",
        nameTextStyle: { color: "#82999e", fontSize: 10, padding: [0, 0, 0, -24] },
        splitLine: { lineStyle: { color: "rgba(181, 207, 205, .1)" } },
        axisLabel: { color: "#82999e", fontSize: 10 },
      },
      // **单子大小是有序的，不是红绿两派。**
      //
      // 原来四档用的是红 #ee6a52 / 橙 / 青 / 绿 #3ca77f —— 那正是驾驶舱的涨跌两色，
      // 于是「超大单」看着像「涨」、「小单」看着像「跌」，而它们表示的只是下单金额档位。
      // 方向已经由柱子在零轴上下说清楚了，颜色该说的是**档位**：一支色相由深到浅。
      series: [
        { name: "超大单", type: "bar", stack: "orders", barMaxWidth: 12, itemStyle: { color: ORDER_SIZES[0] }, data: points.map((point) => toYi(point.super_large_net_inflow)) },
        { name: "大单", type: "bar", stack: "orders", barMaxWidth: 12, itemStyle: { color: ORDER_SIZES[1] }, data: points.map((point) => toYi(point.large_net_inflow)) },
        { name: "中单", type: "bar", stack: "orders", barMaxWidth: 12, itemStyle: { color: ORDER_SIZES[2] }, data: points.map((point) => toYi(point.medium_net_inflow)) },
        { name: "小单", type: "bar", stack: "orders", barMaxWidth: 12, itemStyle: { color: ORDER_SIZES[3] }, data: points.map((point) => toYi(point.small_net_inflow)) },
        {
          name: "主力净流入",
          type: "line",
          // **必须 showSymbol: true。** line 系列的标签是挂在 symbol 上的，
          // showSymbol: false 时 ECharts 连标签一起跳过——不报错，不告警，
          // 图上什么都没有。（同一张图里 bar 系列的标签是能画出来的，
          // 就是靠这个差别定位到的。）symbolSize 3 顺便标出真正的交易日。
          showSymbol: true,
          symbol: "circle",
          symbolSize: 3,
          smooth: 0.24,
          lineStyle: { width: 2, color: BEACON },
          itemStyle: { color: BEACON },
          data: points.map((point) => toYi(point.main_net_inflow)),
          // **把数标在线上。**
          //
          // 四档柱子看得出结构，看不出「这一天到底净流入还是净流出」——
          // 而那是这张图最先要回答的问题。标的是主力净流入（超大单 + 大单），
          // 也就是右栏那个「今日主力 净流出 399 亿」的同一个数。
          //
          // **不能标四档之和**：那个数恒等于零。四档是对同一笔成交的分解，
          // 每一笔买都有对应的卖，加起来必然抵消（实测最后一天四档相加是
          // -0.00004 亿）。「流入减流出」在这份数据里不是四档相加，是主力那一档。
          label: {
            show: true,
            position: "top",
            distance: 5,
            fontFamily: "SFMono-Regular, Consolas, monospace",
            fontSize: 9,
            color: BEACON,
            formatter: (item: { value: number | null }) =>
              finite(item.value) ? `${item.value > 0 ? "+" : ""}${Math.round(item.value)}` : "",
          },
          // 三十个数挤在一起会糊成一片：让 ECharts 藏掉压住的那些，
          // 留下的正好是幅度大的那几天——那也是唯一值得记住的几天。
          labelLayout: { hideOverlap: true },
          z: 5,
        },
      ],
    }, true);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [points]);

  return <div className="cockpit-flow-chart" ref={boxRef} role="img" aria-label="全 A 最近三十个交易日资金流动图" />;
}

function metricText(view: HeatmapView, value: number | null): string {
  if (!finite(value)) return "—";
  const sign = view.metric_kind === "diverging" && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(view.metric_unit ? 2 : 0)}${view.metric_unit}`;
}

function MarketTideMap({ view, selected, onSelect }: {
  view: HeatmapView;
  selected: string;
  onSelect: (name: string) => void;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  // 首屏同时画 100 多个行业时，ECharts 会为了避让把所有文字都藏掉。
  // 数据仍取完整全 A，市场脉搏与行业排行也仍用全量；主图只铺市值最大的
  // 60 个行业，并在界面上明说，不把“全量统计”偷换成“每个行业都可见”。
  const mapTiles = useMemo(() => view.tiles.slice(0, 60), [view.tiles]);
  const range = useMemo(() => quantileRange(
    mapTiles.map((tile) => tile.metric_value).filter(finite),
    view.metric_kind === "diverging",
  ), [mapTiles, view.metric_kind]);
  const ramp = view.metric_kind === "diverging" ? DIVERGING : SEQUENTIAL;

  useEffect(() => {
    if (!boxRef.current || view.tiles.length === 0) return;
    const chart = echarts.getInstanceByDom(boxRef.current)
      ?? echarts.init(boxRef.current, undefined, { renderer: "canvas" });
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: reduceMotion ? 0 : 280,
      animationDurationUpdate: reduceMotion ? 0 : 240,
      animationDelay: 0,
      animationDelayUpdate: 0,
      animationEasing: "cubicOut",
      aria: {
        enabled: true,
        description: `全 A 行业市场潮汐图，面积为${view.size_basis}，颜色为${view.metric_label}；有金色边框的行业包含已建档公司。`,
      },
      tooltip: {
        backgroundColor: "rgba(9, 28, 36, .96)",
        borderColor: "#36545e",
        borderWidth: 1,
        padding: [10, 12],
        textStyle: { color: "#eff7f5", fontSize: 12, lineHeight: 19 },
        confine: true,
        formatter: (params: unknown) => {
          const tile = (params as { data?: HeatmapTile }).data;
          if (!tile || !finite(tile.metric_value)) return "";
          const watchers = tile.watched?.length
            ? `<br/><span style="color:${BEACON}">◆ 已建档：${tile.watched.map((item) => item.name).join("、")}</span>`
            : "";
          return `<strong>${tile.name}</strong><br/>${view.metric_label} <strong>${metricText(view, tile.metric_value)}</strong><br/>${view.size_basis} ${compactCap(tile.size)} · ${tile.count} 家${watchers}`;
        },
      },
      series: [{
        type: "treemap",
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        top: 2,
        right: 2,
        bottom: 2,
        left: 2,
        label: {
          show: true,
          fontFamily: "PingFang SC, Microsoft YaHei, sans-serif",
          formatter: (params: { data?: HeatmapTile }) => {
            const tile = params.data;
            if (!tile || !finite(tile.metric_value)) return "";
            const beacon = tile.watched?.length
              ? `\n{watch|◆ ${tile.watched.slice(0, 2).map((item) => item.name).join(" · ")}${tile.watched.length > 2 ? ` +${tile.watched.length - 2}` : ""}}`
              : "";
            return `{name|${tile.name}}\n{value|${metricText(view, tile.metric_value)}}${beacon}`;
          },
        },
        itemStyle: { borderColor: marketInk.ink.ground, borderWidth: 2, gapWidth: 2 },
        emphasis: { itemStyle: { borderColor: "#eff7f5", borderWidth: 2 } },
        // 颜色自己算而不是交给 visualMap —— 只有先知道这块是什么颜色，
        // 才能决定它该压白字还是深字（浅色格子上的白字是读不了的）。
        data: mapTiles.map((tile) => {
          const fill = rampColor(tile.metric_value ?? range[0], range, ramp);
          const ink = tileInk(fill);
          return {
            ...tile,
            value: [tile.size, tile.metric_value ?? range[0]],
            itemStyle: {
              color: fill,
              borderColor: selected === tile.name ? "#ffffff" : tile.watched?.length ? BEACON : marketInk.ink.ground,
              borderWidth: selected === tile.name ? 4 : tile.watched?.length ? 3 : 2,
              opacity: selected && selected !== tile.name ? 0.56 : 1,
            },
            label: {
              color: ink.strong,
              rich: {
                name: { color: ink.strong, fontSize: 13, fontWeight: 650, lineHeight: 20 },
                value: { color: ink.soft, fontSize: 11, lineHeight: 17, fontFamily: "SFMono-Regular, Consolas, monospace" },
                watch: { color: ink.mark, fontSize: 10, fontWeight: 650, lineHeight: 17 },
              },
            },
          };
        }),
      }],
    }, true);
    chart.off("click");
    chart.on("click", (event) => {
      const name = (event as { data?: { name?: string } }).data?.name;
      if (name) onSelect(name);
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [view, mapTiles, range, ramp, selected, onSelect]);

  return <div className="cockpit-map-chart" ref={boxRef} role="img" aria-label={`全 A ${view.metric_label}市场潮汐图`} />;
}

/**
 * 这份底座数据放了多久 —— **超过一小时才说**，一小时内说了是噪声。
 *
 * 返回空串表示够新。判据用小时不用"是不是今天"：一张开盘三分钟的快照日期就是今天，
 * 而它跟收盘数据差着一整个交易日的行情。
 */
function staleFor(asOf: string | undefined): string {
  if (!asOf || asOf.length < 16) return "";
  const at = Date.parse(asOf.replace(" ", "T"));
  if (Number.isNaN(at)) return "";
  const hours = (Date.now() - at) / 3_600_000;
  if (hours < 1) return "";
  if (hours < 24) return `${Math.floor(hours)} 小时前的数据`;
  return `${Math.floor(hours / 24)} 天前的数据`;
}

function marketState(view: HeatmapView | undefined): { label: string; note: string; upRatio: number; flatRatio: number; downRatio: number } {
  const breadth = view?.breadth;
  if (!breadth || breadth.covered === 0) return { label: "等待行情", note: "同步全市场底座后显示", upRatio: 0, flatRatio: 0, downRatio: 0 };
  const total = breadth.advancing + breadth.declining + breadth.unchanged;
  const upRatio = breadth.advancing / total;
  const flatRatio = breadth.unchanged / total;
  const downRatio = breadth.declining / total;
  const medianMove = breadth.median_change ?? 0;
  if (upRatio >= 0.62) return { label: "普涨", note: `${Math.round(upRatio * 100)}% 股票上涨`, upRatio, flatRatio, downRatio };
  if (downRatio >= 0.62) return { label: "普跌", note: `${Math.round(downRatio * 100)}% 股票下跌`, upRatio, flatRatio, downRatio };
  if (Math.abs(medianMove) <= 0.12) return { label: "平静分化", note: "市场中位涨跌接近零", upRatio, flatRatio, downRatio };
  return { label: "明显分化", note: "涨跌方向没有形成一致性", upRatio, flatRatio, downRatio };
}

function PulseMeter({ label, value, text, max }: { label: string; value: number | null; text: string; max: number }) {
  const width = value === null ? 0 : Math.max(4, Math.min(100, (Math.abs(value) / max) * 100));
  return <div className="cockpit-meter">
    <div><span>{label}</span><strong>{text}</strong></div>
    <i><b style={{ width: `${width}%` }} /></i>
  </div>;
}

function IndustryTide({ view, selected, onSelect }: { view: HeatmapView; selected: string; onSelect: (name: string) => void }) {
  const values = view.tiles.filter((tile) => finite(tile.metric_value));
  if (values.length === 0) return null;
  const diverging = view.metric_kind === "diverging";
  const rows = diverging
    ? [...values].sort((a, b) => (b.metric_value ?? 0) - (a.metric_value ?? 0)).slice(0, 3)
      .concat([...values].sort((a, b) => (a.metric_value ?? 0) - (b.metric_value ?? 0)).slice(0, 3))
    : [...values].sort((a, b) => (b.metric_value ?? 0) - (a.metric_value ?? 0)).slice(0, 6);
  const span = Math.max(...rows.map((row) => Math.abs(row.metric_value ?? 0)), 0.1);
  return <div className="cockpit-tide">
    <div className="cockpit-subhead"><strong>{diverging ? "行业潮汐" : `${view.metric_label}靠前`}</strong><span>点行业定位</span></div>
    <div className="cockpit-tide-list">
      {rows.map((row, index) => {
        const value = row.metric_value ?? 0;
        return <button className={selected === row.name ? "is-selected" : ""} onClick={() => onSelect(row.name)} key={`${row.name}-${index}`}>
          <span>{row.name}</span>
          <i className={diverging ? "is-diverging" : ""}>
            {diverging && <em />}
            <b style={{
              background: diverging ? (value >= 0 ? UP : DOWN) : "#7fb8a2",
              left: diverging ? (value >= 0 ? "50%" : `${50 - (Math.abs(value) / span) * 50}%`) : 0,
              width: diverging ? `${(Math.abs(value) / span) * 50}%` : `${(Math.abs(value) / span) * 100}%`,
            }} />
          </i>
          <strong>{metricText(view, value)}</strong>
        </button>;
      })}
    </div>
  </div>;
}

function FlowSnapshot({ view }: { view: MarketFundFlowView }) {
  const latest = view.points.at(-1);
  const recent = view.points.slice(-5);
  const fiveDayMain = recent.reduce((sum, point) => sum + (point.main_net_inflow ?? 0), 0);
  const positiveDays = recent.filter((point) => (point.main_net_inflow ?? 0) > 0).length;
  const orders: Array<{ label: string; value: number | null | undefined; tone: string }> = [
    { label: "超大单", value: latest?.super_large_net_inflow, tone: "is-super" },
    { label: "大单", value: latest?.large_net_inflow, tone: "is-large" },
    { label: "中单", value: latest?.medium_net_inflow, tone: "is-medium" },
    { label: "小单", value: latest?.small_net_inflow, tone: "is-small" },
  ];
  const max = Math.max(...orders.map((item) => Math.abs(item.value ?? 0)), 1);
  return <div className="cockpit-flow-snapshot">
    <div className="cockpit-subhead"><strong>资金截面</strong><span>{view.as_of}</span></div>
    <div className="cockpit-flow-callout">
      <span>今日主力</span>
      <strong className={flowTone(latest?.main_net_inflow)}>{finite(latest?.main_net_inflow) && latest.main_net_inflow >= 0 ? "净流入 " : "净流出 "}{flowText(Math.abs(latest?.main_net_inflow ?? 0), false)}</strong>
      <small>近 5 日合计 <b className={flowTone(fiveDayMain)}>{flowText(fiveDayMain)}</b> · {positiveDays}/5 日净流入</small>
    </div>
    <div className="cockpit-flow-orders">
      {orders.map((item) => <div key={item.label}>
        <span><i className={item.tone} />{item.label}</span>
        <em><b className={item.value && item.value < 0 ? "is-negative" : ""} style={{ width: `${Math.max(3, Math.abs(item.value ?? 0) / max * 100)}%` }} /></em>
        <strong className={flowTone(item.value)}>{flowText(item.value)}</strong>
      </div>)}
    </div>
    <p>{view.boundary}</p>
  </div>;
}

function WatchBeacon({ item, onOpen }: { item: WatchlistItem; onOpen: () => void }) {
  const move = item.change_percent;
  return <button className="cockpit-company" onClick={onOpen}>
    <i className={`cockpit-company-status cockpit-company-status--${item.thesis_status}`} />
    <span><strong>{item.name}</strong><small>{item.symbol} · {item.industry}</small></span>
    <em>{item.latest_price === null ? "—" : `¥${item.latest_price.toFixed(2)}`}</em>
    <b className={move === null || move === 0 ? "" : move > 0 ? "quote-up" : "quote-down"}>{move === null ? "—" : `${move > 0 ? "+" : ""}${move.toFixed(2)}%`}</b>
  </button>;
}

export function MarketCockpit({ dashboard, actions, onOpenCompany, onOpenMarket, onOpenCompanies, onCreateCompany }: {
  dashboard: DashboardSummary;
  actions: CockpitAction[];
  onOpenCompany: (id: number) => void;
  onOpenMarket: () => void;
  onOpenCompanies: () => void;
  onCreateCompany: () => void;
}) {
  const [metric, setMetric] = useState("change_percent");
  const [views, setViews] = useState<Record<string, HeatmapView>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedIndustry, setSelectedIndustry] = useState("");
  const [lensStatuses, setLensStatuses] = useState<Record<string, MarketLensStatus>>({});
  const [fundFlow, setFundFlow] = useState<MarketFundFlowView | null>(null);
  const [fundFlowError, setFundFlowError] = useState("");

  const loadMetric = useCallback(async (nextMetric: string) => {
    if (views[nextMetric]) return;
    setLoading(true);
    try {
      // 云图展示市值最大的 60 个行业；接口中的市场广度仍基于全部 A 股计算。
      const next = await getHeatmap("all", nextMetric, 60);
      setViews((current) => ({ ...current, [nextMetric]: next }));
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "市场底座暂时不可用");
    } finally {
      setLoading(false);
    }
  }, [views]);

  useEffect(() => {
    let live = true;
    setLoading(true);
    // **主图只等一个镜头。**
    //
    // 首屏要四份数据：当日涨跌铺主图，另外三个只为右栏那三行中位数。原来用
    // Promise.all 等齐四份才画——于是首屏由**最慢的那一发**决定，实测 1.5 秒。
    // 四发同时打出去不变，变的是各自到各自填：涨跌一到主图就出来了。
    //
    // 顺带修掉一个更难看的行为：等齐的写法里，三个中位数随便哪个失败都会把
    // 整张市场图换成一行报错。现在只有当日涨跌能决定「有没有图」，
    // 中位数缺一个就是那一行显示「暂无」。
    const settle = (item: HeatmapView) => {
      if (live) setViews((current) => ({ ...current, [item.metric]: item }));
    };
    getHeatmap("all", "change_percent", 60)
      .then((item) => { settle(item); if (live) setError(""); })
      .catch((caught) => { if (live) setError(caught instanceof Error ? caught.message : "市场底座暂时不可用"); })
      .finally(() => { if (live) setLoading(false); });
    for (const key of ["turnover_rate", "abs_change", "attention_index"]) {
      getHeatmap("all", key, 60).then(settle).catch(() => { /* 那一行显示「暂无」就够了 */ });
    }
    return () => { live = false; };
  }, []);

  useEffect(() => {
    let live = true;
    getMarketLensStatuses()
      .then((items) => { if (live) setLensStatuses(Object.fromEntries(items.map((item) => [item.metric, item]))); })
      .catch(() => { /* 不影响当天云图；区间镜头保持不可点。 */ });
    getMarketFundFlow()
      .then((view) => { if (live) { setFundFlow(view); setFundFlowError(""); } })
      .catch((caught) => { if (live) setFundFlowError(caught instanceof Error ? caught.message : "资金流数据暂时不可用"); });
    return () => { live = false; };
  }, []);

  const chooseLens = (nextMetric: string) => {
    const status = lensStatuses[nextMetric];
    if (GUARDED_LENSES.has(nextMetric) && (!status || !status.available)) return;
    setMetric(nextMetric);
    setSelectedIndustry("");
    if (nextMetric !== "capital_flow" && !views[nextMetric]) void loadMetric(nextMetric);
  };

  const isFundFlow = metric === "capital_flow";
  const current = (isFundFlow ? views.change_percent : views[metric]) ?? views.change_percent;
  const changeView = views.change_percent;
  const state = marketState(changeView);
  const breadth = changeView?.breadth;
  const totalBreadth = breadth ? breadth.advancing + breadth.declining + breadth.unchanged : 0;
  const turnover = median(views.turnover_rate?.tiles.map((tile) => tile.metric_value) ?? []);
  const volatility = median(views.abs_change?.tiles.map((tile) => tile.metric_value) ?? []);
  const attention = median(views.attention_index?.tiles.map((tile) => tile.metric_value) ?? []);
  const selectedTile = current?.tiles.find((tile) => tile.name === selectedIndustry);
  const watchedIds = new Set(selectedTile?.watched?.map((item) => item.company_id) ?? []);
  const visibleCompanies = (watchedIds.size
    ? dashboard.watchlist.filter((item) => watchedIds.has(item.id))
    : [...dashboard.watchlist].sort((a, b) => Math.abs(b.change_percent ?? 0) - Math.abs(a.change_percent ?? 0)))
    .slice(0, 6);
  const ring = `conic-gradient(${UP} 0 ${state.upRatio * 100}%, ${FLAT} ${state.upRatio * 100}% ${(state.upRatio + state.flatRatio) * 100}%, ${DOWN} ${(state.upRatio + state.flatRatio) * 100}% 100%)`;

  return <section className="deck market-cockpit" aria-labelledby="market-cockpit-title">
    <header className="cockpit-head">
      <div>
        {/* **印数据自己的日期，不是今天。**
            云图和市场脉搏吃的是 market_universe，那张表由计划任务刷；
            顶栏那个「同步实时行情」只刷你建过档的公司，根本不碰它。
            原来这里印 dashboard.as_of（今天），于是开盘大涨的当天，页面顶着今天的
            日期显示上一个交易日收盘的「69% 股票下跌」——
            **日期标签在替一份过期数据背书**，比不写日期糟得多。 */}
        {/* **印到分钟，不只是日期。**
            实测 2026-08-17：底座 09:33 刷完（开盘后三分钟），整个交易日都停在
            「69% 股票下跌」，而当天收 +1.26%。日期是对的、时间是错的 ——
            **只印日期的话，一张开盘三分钟的快照看起来跟收盘数据一模一样。**
            超过一小时就明说多久以前，别让人自己去算。 */}
        <span className="cockpit-kicker">
          A-SHARE MARKET · {(changeView?.as_of || dashboard.as_of).slice(0, 16).replace("T", " ")}
          {staleFor(changeView?.as_of) && <em className="cockpit-stale">{staleFor(changeView?.as_of)}</em>}
          {/* **降级要说出来。** 备用源只给价格和涨跌幅，没有市值和 PE ——
              而云图的面积按市值算、估值镜头按 PE 算。不说的话它照常画出一张图，
              只是面积和估值是缺的或旧的，而那种错在图上完全看不出来。 */}
          {changeView?.degraded && <em className="cockpit-stale" title={changeView.source}>
            行情走的备用源 · 缺{(changeView.missing_fields ?? []).join("、")}
          </em>}
        </span>
        <h2 id="market-cockpit-title">A 股市场潮汐</h2>
        <p>整张市场是底图，金色灯塔是你已经建立档案的公司。</p>
      </div>
      <div className="cockpit-lenses" role="tablist" aria-label="切换市场观察维度">
        {LENSES.map((lens) => {
          const status = lensStatuses[lens.metric];
          const unavailable = GUARDED_LENSES.has(lens.metric) && (!status || !status.available);
          const suffix = unavailable
            ? !status ? "检查中" : status.required_days ? `${status.trading_days}/${status.required_days}` : "待接入"
            : "";
          return <button
            role="tab"
            aria-selected={metric === lens.metric}
            aria-disabled={unavailable}
            className={`${metric === lens.metric ? "is-active" : ""}${unavailable ? " is-unavailable" : ""}`}
            onClick={() => chooseLens(lens.metric)}
            title={status?.message}
            key={lens.metric}
          >{lens.label}{suffix && <small>{suffix}</small>}</button>;
        })}
      </div>
    </header>

    <div className="cockpit-grid">
      <div className="cockpit-map-wrap">
        <div className="cockpit-map-meta">
          {isFundFlow
            ? <div><strong>全 A 资金河流</strong><span>{fundFlow ? `最近 ${Math.min(30, fundFlow.points.length)} 个交易日 · 截至 ${fundFlow.as_of} · 单位亿元` : "正在读取真实资金流"}</span></div>
            : <div><strong>{current?.scope_label ?? "全 A"}</strong><span>{current ? `${current.universe_total} 只 · ${current.metric_label} · 主图显示市值前 ${Math.min(60, current.tiles.length)} 行业` : "正在读取市场"}</span></div>}
          {!isFundFlow && <button onClick={onOpenMarket}>打开完整市场云图 →</button>}
        </div>
        {isFundFlow && fundFlowError && <div className="cockpit-map-empty">{fundFlowError}</div>}
        {isFundFlow && !fundFlowError && !fundFlow && <div className="cockpit-map-empty">正在汇入真实资金流…</div>}
        {isFundFlow && fundFlow && <CapitalFlowChart view={fundFlow} />}
        {!isFundFlow && error && <div className="cockpit-map-empty">{error}<button onClick={() => void loadMetric(metric)}>重新读取</button></div>}
        {!isFundFlow && !error && loading && !current && <div className="cockpit-map-empty">正在铺开真实市场数据…</div>}
        {!isFundFlow && !error && current && current.tiles.length === 0 && <div className="cockpit-map-empty">“{current.metric_label}”正在积累真实历史；数据就绪前不展示残缺区间。</div>}
        {!isFundFlow && !error && current && current.tiles.length > 0 && <MarketTideMap view={current} selected={selectedIndustry} onSelect={(name) => setSelectedIndustry((value) => value === name ? "" : name)} />}
        {isFundFlow && fundFlow && <div className="cockpit-flow-legend">
          <span><i className="is-super" />超大单</span><span><i className="is-large" />大单</span><span><i className="is-medium" />中单</span><span><i className="is-small" />小单</span><span><i className="is-main" />主力净流入</span><small>{fundFlow.source}</small>
        </div>}
        {!isFundFlow && current && <div className="cockpit-map-legend">
          <span><i className="beacon" />已建档公司</span>
          <span>{current.metric_kind === "diverging" ? "绿：下降" : "浅：较低"}</span>
          <em />
          <span>{current.metric_kind === "diverging" ? "红：上升" : "金：较高"}</span>
          <small>{current.metric_note}</small>
        </div>}
      </div>

      <aside className="cockpit-rail">
        <div className="cockpit-pulse">
          <div className="cockpit-subhead"><strong>市场脉搏</strong><span>{totalBreadth ? `覆盖 ${totalBreadth} 只` : "等待行情"}</span></div>
          <div className="cockpit-pulse-main">
            <div className="cockpit-pulse-ring" style={{ background: ring }}><div><strong>{state.label}</strong><span>{breadth?.median_change === null || breadth?.median_change === undefined ? "—" : `${breadth.median_change > 0 ? "+" : ""}${breadth.median_change.toFixed(2)}%`}</span></div></div>
            <div className="cockpit-pulse-copy"><strong>{state.note}</strong><span><i style={{ background: UP }} />涨 {breadth?.advancing ?? 0}</span><span><i style={{ background: DOWN }} />跌 {breadth?.declining ?? 0}</span></div>
          </div>
          <PulseMeter label="行业换手中位" value={turnover} text={turnover === null ? "暂无" : `${turnover.toFixed(2)}%`} max={8} />
          <PulseMeter label="行业波动中位" value={volatility} text={volatility === null ? "暂无" : `${volatility.toFixed(2)}%`} max={3} />
          <PulseMeter label="行业关注中位" value={attention} text={attention === null ? "暂无" : attention.toFixed(0)} max={100} />
        </div>
        {isFundFlow && fundFlow
          ? <FlowSnapshot view={fundFlow} />
          : current && <IndustryTide view={current} selected={selectedIndustry} onSelect={(name) => setSelectedIndustry((value) => value === name ? "" : name)} />}
      </aside>
    </div>

    <div className="cockpit-beacons">
      <div className="cockpit-beacons-head">
        <div><strong>{selectedIndustry ? `${selectedIndustry}里的我的公司` : "我的公司"}</strong><span>{
          // **没认出你是谁的时候，不许报一个数。** 游客域一行都匹配不到，
          // 那份档案处处为 0 —— 报「已建档 0 家」是在陈述一件没查证过的事。
          dashboard.viewer_is_guest ? "还没认出你是谁"
            : selectedIndustry && watchedIds.size === 0 ? "这个行业暂时没有已建档公司"
              : `已建档 ${dashboard.watchlist.length} 家`}</span></div>
        <button onClick={onOpenCompanies}>查看全部 →</button>
      </div>
      <div className="cockpit-company-list">
        {/* **游客态不能穿新用户的衣服。**
            两者的空列表长得一样，下一步却完全相反：一个该去建档，
            一个该去登录。2026-08-15 线上那次，站主看到的正是这句
            「建立第一家公司 →」，而他名下有 6 家。 */}
        {visibleCompanies.length === 0 && (dashboard.viewer_is_guest
          ? <div className="cockpit-company-empty">
              <span>还没认出你是谁，所以这里暂时读不到你的公司档案。稍等一下会自动重试，或者刷新一下这一页。</span>
            </div>
          : <div className="cockpit-company-empty">
              <span>建立第一家公司档案后，它会作为灯塔出现在市场图上。</span>
              <button className="cockpit-empty-cta" onClick={onCreateCompany}>建立第一家公司 →</button>
            </div>)}
        {visibleCompanies.map((item) => <WatchBeacon item={item} onOpen={() => onOpenCompany(item.id)} key={item.id} />)}
      </div>
      {actions.some((action) => action.count > 0) && <div className="cockpit-actions" aria-label="研究待办">
        <span>研究待办</span>
        {actions.filter((action) => action.count > 0).map((action) => <button className={`cockpit-action cockpit-action--${action.tone}`} onClick={action.onClick} key={action.label}>{action.label}<b>{action.count}</b></button>)}
      </div>}
    </div>
  </section>;
}
