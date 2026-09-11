/**
 * 这家公司靠什么赚钱：年报分部附注里的收入占比与各块毛利率。
 *
 * **这是真数据。** 同一页上的经营关系线索每条都标着「待证实」（模型的世界知识），
 * 而这一块每一行都能在年报的分部附注里对上。所以两者在页面上要分得开，
 * 不能混着排——不然"待证实"三个字会被读成整页的免责声明，而不是只针对那一块。
 *
 * ## 为什么占比和毛利率必须同屏
 *
 * 只画收入占比是个陷阱：它会让人以为最大那块就是最重要的。
 * 实测茅台 2025 年报——茅台酒占收入 86.8%、毛利率 93.5%；系列酒占 13.2%、
 * 毛利率 76.1%。**结论要两个数一起才成立**：大头同时也是高毛利的那块。
 * 反过来的公司也常见（大头低毛利、小块高毛利），而只看占比会完全错过。
 *
 * 所以每一段的**宽度是收入占比、下面一行直接写毛利率**。
 * 没有把毛利率也编码成颜色深浅——那需要一根图例才能读，而一个数字不需要。
 *
 * ## 为什么是一条堆叠条，不是饼图
 *
 * 要看的是"几块、各占多少、谁最大"。堆叠条把它压成一维，长度可以直接比；
 * 饼图要靠角度比大小，而人比角度比比长度差得多。分部通常只有 2–5 块，
 * 一条足够，而且三个口径叠起来还能横向对齐着看。
 *
 * ## 「其他(补充)」
 *
 * 数据源补的差额行，占比常常是 0.04%、偶尔是负的。保留不丢——丢了各块加起来
 * 就不等于 100%，看图的人会以为我们算错了。但它不是业务分部，画成灰色并标注。
 */

import { useState } from "react";

import type { SegmentView } from "../api";

/** `=== null` 拦不住 `undefined`。isFinite 同时挡住 null、undefined 和 NaN。 */
function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// 单色相按明度分级：分部之间**是有序的**（按收入占比从大到小排），
// 有序的东西用明度而不是色相。四个以上的分部若用四个色相，
// 又会掉进红绿混淆那个坑，而这里根本不需要色相来区分——顺序和标签已经够了。
const STEPS = ["#1e5f9e", "#2a78d6", "#6ba3e0", "#a8c8ea"];
const FILLER_COLOR = "#c9ced2";

const DIMENSION_HINT: Record<string, string> = {
  产品: "卖的是什么",
  行业: "算哪个行业",
  地区: "卖到哪里",
};

export function SegmentMix({ data, onRefresh, refreshing }: {
  data: SegmentView;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const dimensions = data.dimensions;
  const [active, setActive] = useState(0);

  if (dimensions.length === 0) {
    return <div className="segment-block">
      <div className="segment-head">
        <h3>它靠什么赚钱</h3>
        <button className="page-action" onClick={onRefresh} disabled={refreshing}>
          {refreshing ? "正在拉取…" : "同步主营构成"}
        </button>
      </div>
      <div className="empty-state">{data.boundary}</div>
    </div>;
  }

  const current = dimensions[Math.min(active, dimensions.length - 1)];
  // 差额行排到最后：它不是业务分部，混在中间会打断"从大到小"的读法
  const items = [...current.items].sort((a, b) =>
    Number(a.filler) - Number(b.filler) || (b.revenue_share ?? 0) - (a.revenue_share ?? 0));

  return <div className="segment-block">
    <div className="segment-head">
      <div>
        <h3>它靠什么赚钱</h3>
        <p>{data.report_date} 年报的分部附注。<strong>这是披露过的事实</strong>，
           不是推断——跟下面的经营关系线索不同，那些每条都还等着你去核对。</p>
      </div>
      <button className="page-action" onClick={onRefresh} disabled={refreshing}>
        {refreshing ? "正在拉取…" : "重新同步"}
      </button>
    </div>

    {dimensions.length > 1 && <div className="chart-range-group" role="group" aria-label="口径">
      {dimensions.map((dim, index) => (
        <button type="button" key={dim.key}
                className={`chart-range${index === active ? " chart-range--on" : ""}`}
                onClick={() => setActive(index)}>
          按{dim.key}<em>{DIMENSION_HINT[dim.key] ?? ""}</em>
        </button>
      ))}
    </div>}

    <div className="segment-bar" role="img"
         aria-label={items.map((s) => `${s.segment} 占收入 ${s.revenue_share}%，毛利率 ${s.gross_margin ?? "未披露"}%`).join("；")}>
      {items.map((item, index) => (
        <i key={item.segment}
           style={{
             flexGrow: Math.max(item.revenue_share ?? 0, 0.4),   // 0.04% 的差额行也要看得见
             background: item.filler ? FILLER_COLOR : STEPS[Math.min(index, STEPS.length - 1)],
           }}
           title={`${item.segment}　收入 ${item.revenue_share}%　毛利率 ${item.gross_margin ?? "—"}%`} />
      ))}
    </div>

    <ul className="segment-list">
      {items.map((item, index) => (
        <li key={item.segment} className={item.filler ? "segment-row--filler" : ""}>
          <i style={{ background: item.filler ? FILLER_COLOR : STEPS[Math.min(index, STEPS.length - 1)] }} />
          <span className="segment-name">{item.segment}</span>
          <strong>{num(item.revenue_share)?.toFixed(1) ?? "—"}<span>%</span></strong>
          {/* 毛利率写成数字而不是编码成颜色深浅：数字不需要图例就能读 */}
          <em>毛利率 {num(item.gross_margin) === null ? "未披露" : `${num(item.gross_margin)!.toFixed(1)}%`}</em>
        </li>
      ))}
    </ul>

    <p className="chart-note">
      宽度是收入占比，后面那个数是这一块自己的毛利率——<strong>两个数要一起看</strong>。
      只看占比会以为最大那块就是最重要的，但常见的情况是大头低毛利、小块才赚钱。
      {items.some((s) => s.filler) && "灰色那截是数据源补的差额，不是业务分部。"}
    </p>
  </div>;
}
