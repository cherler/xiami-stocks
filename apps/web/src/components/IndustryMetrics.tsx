/**
 * 行业特有指标：这门生意该盯的那几个数。
 *
 * ## 为什么每条指标都要带着公式和科目
 *
 * 「净息差 2.1%」这种数，编出来的跟真的长得一模一样，而你会拿它去做判断。
 * 所以这里每一条都摊开写着**用了哪几个科目、公式是什么**——
 * 点开就能对着年报核。这是"模型不参与"唯一有意义的证明方式：
 * 不是嘴上说说，是让你能查。
 *
 * ## 折线不画坐标轴
 *
 * 这几条线的用途是"看方向和拐点"，不是读具体数值——具体数值就在旁边写着。
 * 加坐标轴会把一个瞄一眼的东西变成一张要读的图，而这一页有五到七条指标，
 * 五到七张要读的图等于没有图。
 *
 * ## 算不出来的排在后面，并且说清楚为什么
 *
 * 银行的报表上没有营业成本和研发费用，通用那三条对它全是空的。
 * 空着排在最上面会让人以为功能坏了；而直接不显示，你就不知道
 * 是"这家公司没数据"还是"这个指标不适用"。所以排到后面、写明缺哪个科目。
 */

import { Source } from "./Source";
import { useEffect, useState } from "react";
import { Boundary } from "./Boundary";

import { getIndustryMetrics, type IndustryMetricRow, type IndustryMetricsView } from "../api";

function rich(text: string) {
  return text.split("\n\n").map((paragraph, block) =>
    <p key={block}>{paragraph.split(/\*\*/).map((part, index) =>
      index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>)}</p>);
}

/** 迷你折线：只看方向和拐点，所以不画轴、不标点。 */
function Spark({ series }: { series: { report_date: string; value: number }[] }) {
  if (series.length < 2) return null;
  const values = series.map((point) => point.value);
  const low = Math.min(...values);
  const span = Math.max(...values) - low || 1;
  const width = 132;
  const height = 30;
  const step = width / (series.length - 1);
  const path = values
    .map((value, index) => `${index === 0 ? "M" : "L"}${(index * step).toFixed(1)},${(height - ((value - low) / span) * height).toFixed(1)}`)
    .join(" ");
  const lastX = width;
  const lastY = height - ((values[values.length - 1] - low) / span) * height;
  return <svg className="im-spark" width={width} height={height} viewBox={`0 0 ${width} ${height}`}
    role="img" aria-label={`${series.length} 期走势，从 ${series[0].report_date} 到 ${series[series.length - 1].report_date}`}>
    <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5"
      strokeLinejoin="round" strokeLinecap="round" />
    <circle cx={lastX} cy={lastY} r="2.5" fill="currentColor" />
  </svg>;
}

function Row({ row }: { row: IndustryMetricRow }) {
  const [open, setOpen] = useState(false);
  // **一行三列：名字 · 走势 · 数字。**
  //
  // 上一版是「名字靠左 + margin-left:auto 把数字推到最右」，中间空掉七百像素；
  // 走势图又单独占一行、也贴在最左边。于是眼睛要横跨两片空白才能把
  // 「这个指标叫什么」和「它是多少」对上，而这两件事本来就是一句话。
  // 现在走势图填在中间，三样在同一行上，从左读到右就是一句话。
  return <article className={`im-row${row.applicable ? "" : " im-row--na"}`}>
    <div className="im-name">
      <span className={`im-scope${row.scope === "行业特有" ? " im-scope--own" : ""}`}>{row.scope}</span>
      <b>{row.label}</b>
      {/* 方向跟着数字走，不再单独占一行 —— 它是这个数的口径，不是一条独立信息。 */}
      {row.applicable && row.good && <em className="im-good">
        {row.good === "高" ? "越高越好" : "越低越好"}
      </em>}
    </div>

    <div className="im-mid">
      {row.applicable
        // 两个点连不成趋势，而两个点画出来的线看着跟趋势一模一样。
        ? (row.trendable ? <Spark series={row.series} />
            : <span className="im-thin">只有 {row.series.length} 期</span>)
        : <span className="im-thin">不适用 · 报表没有{row.missing.map((name) => `「${name}」`).join("、")}</span>}
    </div>

    <div className="im-num">
      {/* 出处跟数字同一行。原来期数在下面 im-asof 那一行——**隔着一张走势图，
          等于这个数自己不说自己是哪一期的**，而这些指标里有几个只有年报才披露。 */}
      {row.latest
        ? <span className="im-value">{row.latest.value}<em>{row.unit}</em></span>
        : <span className="im-value im-value--none">算不出来</span>}
      <span className="im-meta">
        {row.latest && <Source kind={row.annual_only ? "年报" : "财报"} at={row.latest.report_date} />}
        {row.change !== null && <span className="im-change">
          {row.change > 0 ? "+" : ""}{row.change} {row.compare_note}
        </span>}
      </span>
    </div>

    <button className="text-button im-toggle" type="button" onClick={() => setOpen(!open)}>
      {open ? "收起" : "这个数是怎么算的"}
    </button>
    {open && <div className="im-detail">
      <p className="im-formula">{row.formula}</p>
      <div className="im-why">{rich(row.why)}</div>
    </div>}
  </article>;
}

export function IndustryMetrics({ companyId }: { companyId: number }) {
  const [view, setView] = useState<IndustryMetricsView | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setView(null); setError("");
    getIndustryMetrics(companyId)
      .then((next) => { if (live) setView(next); })
      .catch((caught) => { if (live) setError(caught instanceof Error ? caught.message : "读取失败"); });
    return () => { live = false; };
  }, [companyId]);

  if (error) return <p className="form-error">{error}</p>;
  if (!view) return <div className="empty-state">正在算…</div>;

  const available = view.rows.filter((row) => row.latest !== null).length;

  return <div className="industry-metrics">
    <div className="im-headline">
      <div><b>{view.resolved || "通用经营指标"}</b><span>　{available}/{view.rows.length} 项可用</span></div>
      <details className="im-method-note">
        <summary>指标口径</summary>
        <p>行业：{Object.entries(view.industry_sources).map(([label, value]) => `${label} ${value || "—"}`).join(" ｜ ")}</p>
        {view.note && <div>{rich(view.note)}</div>}
      </details>
    </div>
    {view.rows.map((row) => <Row key={row.key} row={row} />)}
    <Boundary text={view.boundary} />
  </div>;
}
