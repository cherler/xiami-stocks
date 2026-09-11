/**
 * 这家公司在同行业里站在哪儿。
 *
 * **单个数字判断不了贵贱。** 「PE 21 倍」对白酒算便宜、对银行算贵得离谱；
 * 「毛利率 90%」在白酒里普通、在制造业里不可能。一个数字摆在那儿，
 * 只能去猜，而搜出来的答案永远是"看行业"。所以这里不评价绝对值，只给位置。
 *
 * ## 为什么是分位带，不是柱状图
 *
 * 要回答的是「在同行的分布里落在哪」——那是**一个点相对一片分布**的问题。
 * 柱状图比的是几个离散对象的大小，答不了这个；把同行全画成柱子（19 根）
 * 也没用，人不会去数第几根。分位带把分布压成一条线，位置一眼可见。
 *
 * 每行各自缩放。四项指标单位都不一样（倍 / %），共用一根轴毫无意义——
 * 而共用轴最坏的地方是它看起来可以比较。
 *
 * ## 颜色
 *
 * 只有一个带颜色的标记：这家公司（#2a78d6，与公司时间轴同一支蓝，已过
 * validate_palette）。分布带本身是中性灰——**它是背景，不是第二个类别**，
 * 给它一个色相会让人以为那是另一组数据。
 *
 * 也刻意不做"绿=好、红=坏"：分位只是排位，不是结论。同行整体贵的时候，
 * 排在便宜的一头照样可能是贵的，上色等于替人下了一个我们没有依据的判断。
 */

import type { PeerPositionView } from "../api";

const MINE = "#2a78d6";

/** 把值映射到 0–100 的横向位置。轴取 p10–p90，公司值超出时把轴撑开。 */
function scale(metric: PeerPositionView["metrics"][number]) {
  const value = metric.value;
  const low = Math.min(metric.p10, value ?? metric.p10);
  const high = Math.max(metric.p90, value ?? metric.p90);
  const span = high - low || 1;
  return (x: number) => ((x - low) / span) * 100;
}

/** 站内统一的数字守卫。
 *
 * **`!== null` 拦不住 `undefined`。** 少一个字段不报错、不告警，
 * 只在渲染时炸成一句「Cannot read properties of undefined (reading 'toFixed')」——
 * 这句话对定位毫无帮助，而线上数据跟本地不一样，照着代码看是猜不出来的。
 * `Number.isFinite` 同时挡住 null、undefined 和 NaN，跟 formatMoney / signedPct 一致。
 */
function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function PeerPosition({ data }: { data: PeerPositionView }) {
  if (data.metrics.length === 0) {
    return <div className="empty-state">{data.note}</div>;
  }

  return <>
    <div className="pp-rows">
      {data.metrics.map((metric) => {
        const at = scale(metric);
        const value = num(metric.value);
        const has = value !== null;
        return (
          <div className="pp-row" key={metric.key}>
            <div className="peer-label">
              <strong>{metric.label}</strong>
              <em>同行 {metric.sample} 家</em>
            </div>

            <div className="peer-strip" role="img"
                 aria-label={`${metric.label}：同行 ${metric.sample} 家，中位数 ${metric.p50}${metric.unit}` +
                   (has ? `，本公司 ${value.toFixed(2)}${metric.unit}，排在第 ${metric.percentile} 分位` : "，本公司无数据")}>
              {/* 两端 10% 掐掉：A 股每个行业都有几家 PE 三千倍的（微利边缘），
                  全量铺开会把整条带子拉成一根针 */}
              <i className="peer-band peer-band--wide"
                 style={{ left: `${at(metric.p10)}%`, width: `${at(metric.p90) - at(metric.p10)}%` }} />
              <i className="peer-band peer-band--mid"
                 style={{ left: `${at(metric.p25)}%`, width: `${at(metric.p75) - at(metric.p25)}%` }} />
              <i className="peer-median" style={{ left: `${at(metric.p50)}%` }} title={`中位数 ${metric.p50}${metric.unit}`} />
              {has && <i className="peer-mine" style={{ left: `${at(value)}%`, background: MINE }} />}
            </div>

            <div className="pp-value">
              {has ? <>
                <strong>{value.toFixed(2)}<span>{metric.unit}</span></strong>
                {/* 文字写死方向，不靠颜色 —— 分位是排位，"高"本身不等于好 */}
                <em>第 {metric.percentile} 分位 · 中位 {metric.p50}{metric.unit}</em>
              </> : <em>没有数据</em>}
            </div>
          </div>
        );
      })}
    </div>

    <div className="peer-legend">
      <span><i className="peer-key peer-key--wide" />同行的 10%–90%</span>
      <span><i className="peer-key peer-key--mid" />中间半数</span>
      <span><i className="peer-key peer-key--median" />中位数</span>
      <span><i className="peer-key peer-key--mine" style={{ background: MINE }} />本公司</span>
    </div>
    <p className="chart-note">{data.industry && `行业：${data.industry}　`}{data.note}</p>
  </>;
}
