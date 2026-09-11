/**
 * 同业对照：同一行业里真正的同行（全市场口径）。
 *
 * 名字带 Market 前缀：App.tsx 里另有一个 PeerTable，那张比的是研究池里
 * 同行业的公司，行业页还在用。两张表的比较对象根本不同，不能共用一个名字。
 *
 * ## 换掉了什么
 *
 * 原来这张表比的是**研究池里恰好同行业的那几家**——茅台旁边可能只站着一家洋河，
 * 也可能一家都没有。那不是同业对照，是"我碰巧关注的几家"：
 * 样本是自己挑的，比出来的高低就没有意义。
 *
 * 现在取全市场底座里同行业的公司。行业口径也换了：档案里写的是证监会门类
 * 「酒、饮料和精制茶制造业」，底座里是申万二级「白酒Ⅱ」——**后者才是能比的粒度**，
 * 前者会把白酒和饮料、茶叶放在一起。
 *
 * ## 中位数那一行
 *
 * 按**全行业**算，不是按表里这十几家算，并且单独标出来。
 * 表是按市值截断过的，拿截断后的样本算中位数会系统性偏向大公司——
 * 而人看表时会不自觉地拿"表里这些"当成"行业整体"。
 *
 * ## 不上色
 *
 * 数字不做红绿。PE 低不等于好（可能是市场认为它要出事），
 * ROE 高不等于好（可能是高杠杆撑出来的）。上色等于替人下判断，
 * 而这一页的职责是把可比的数字摆齐，判断留给人。
 * 本公司那一行加粗加底色——那是"你在哪"，不是"好不好"。
 */

import type { PeerTableView } from "../api";

const COLUMNS = [
  { key: "total_market_cap", label: "总市值", unit: "亿", scale: 1e8, digits: 0 },
  { key: "pe_ttm", label: "PE(TTM)", unit: "倍", digits: 2 },
  { key: "pb", label: "PB", unit: "倍", digits: 2 },
  { key: "roe", label: "ROE", unit: "%", digits: 2 },
  { key: "gross_margin", label: "毛利率", unit: "%", digits: 1 },
  { key: "revenue_growth", label: "营收同比", unit: "%", digits: 1 },
  { key: "dividend_yield", label: "股息率", unit: "%", digits: 2 },
] as const;

function cell(value: number | null | undefined, scale = 1, digits = 2): string {
  // `=== null` 拦不住 undefined；isFinite 同时挡住三种
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return (value / scale).toFixed(digits);
}

export function MarketPeerTable({ data, onOpenSymbol }: {
  data: PeerTableView;
  onOpenSymbol?: (symbol: string) => void;
}) {
  if (data.rows.length === 0) {
    return <div className="empty-state">{data.note}</div>;
  }

  const self = data.rows.find((row) => row.is_self) ?? null;
  const comparison = [
    { key: "pe_ttm", label: "PE", unit: "倍", digits: 2 },
    { key: "pb", label: "PB", unit: "倍", digits: 2 },
    { key: "roe", label: "ROE", unit: "%", digits: 2 },
    { key: "dividend_yield", label: "股息率", unit: "%", digits: 2 },
  ] as const;

  function relative(current: number | null | undefined, median: number | null | undefined): string {
    if (typeof current !== "number" || typeof median !== "number") return "暂不可比";
    if (Math.abs(current - median) < 0.01) return "接近中位";
    return current < median ? "低于中位" : "高于中位";
  }

  return <>
    {self && <div className="ptable-reading" aria-label={`${self.name}与全行业中位数对照`}>
      {comparison.map((metric) => {
        const current = self[metric.key];
        const median = data.median[metric.key];
        return <article key={metric.key}>
          <span>{metric.label}</span>
          <strong>{cell(current, 1, metric.digits)}<em>{metric.unit}</em></strong>
          <small>{relative(current, median)} · 中位 {cell(median, 1, metric.digits)}</small>
        </article>;
      })}
    </div>}
    <details className="ptable-details">
      <summary>展开同行明细 <span>{data.rows.length} 家代表公司 · 全行业 {data.total} 家</span></summary>
      <div className="ptable-wrap">
      <table className="ptable">
        <thead>
          <tr>
            <th scope="col">公司</th>
            {COLUMNS.map((c) => <th scope="col" key={c.key}>{c.label}<em>{c.unit}</em></th>)}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.symbol} className={row.is_self ? "ptable-self" : ""}>
              <th scope="row">
                {onOpenSymbol
                  ? <button className="text-button" onClick={() => onOpenSymbol(row.symbol)}>{row.name}</button>
                  : <span>{row.name}</span>}
                <em>{row.symbol}</em>
              </th>
              {COLUMNS.map((c) => (
                <td key={c.key}>
                  {cell(row[c.key as keyof typeof row] as number | null,
                        "scale" in c ? c.scale : 1, c.digits)}
                </td>
              ))}
            </tr>
          ))}
          {/* 中位数单独一行并标明口径：人看表时会不自觉地拿"表里这些"当成"行业整体" */}
          <tr className="ptable-median">
            <th scope="row"><span>全行业中位数</span><em>{data.total} 家</em></th>
            {COLUMNS.map((c) => (
              <td key={c.key}>
                {cell(data.median[c.key], "scale" in c ? c.scale : 1, c.digits)}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      </div>
      <p className="chart-note">{data.note}空白表示底座里还没有这项数据，不是 0。</p>
    </details>
  </>;
}
