import { Link2, TriangleAlert } from "lucide-react";

import type { ChainCompareCompany, ChainCompareNode, ChainCompareView } from "../types";

/**
 * 按环节横排。
 *
 * 为什么底图之外还要这一屏:行业分类(申万、证监会)是按公司主营分的,
 * 分不出「同一种材料在两条链上是两个市场」——铜箔在锂电和 PCB、玻璃在光伏和显示,
 * 是同一批公司面对完全不同的需求曲线。底图把公司钉在环节上,这里才能按环节横比。
 *
 * 三条显示纪律:
 * - 取不到行情的公司照样列出来、格子留空,不从名单里删掉;
 * - 每一环显式标出「几家没行情」,否则中位数会被悄悄算在少数几家身上;
 * - 整列没数据的指标(本机底座还没攒够交易日的涨跌幅)直接收起并说明——
 *   一列全是「—」和「这批公司都没涨」在屏幕上长得一模一样。
 */

function yi(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${(value / 1e8).toLocaleString("zh-CN", { maximumFractionDigits: 0 })} 亿`;
}

function num(value: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function pct(value: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toLocaleString("zh-CN", { maximumFractionDigits: digits })}%`;
}

type Column = {
  key: keyof ChainCompareCompany;
  label: string;
  /** 这一列没数据时怎么跟人解释,而不是让它静静地空着 */
  emptyNote: string;
  render: (company: ChainCompareCompany) => string;
};

const COLUMNS: Column[] = [
  { key: "total_market_cap", label: "市值", emptyNote: "全市场底座里没有市值", render: (c) => yi(c.total_market_cap) },
  { key: "revenue", label: "营收", emptyNote: "没有营收", render: (c) => yi(c.revenue) },
  { key: "net_profit", label: "净利", emptyNote: "没有净利润", render: (c) => yi(c.net_profit) },
  { key: "pe_ttm", label: "PE(TTM)", emptyNote: "没有市盈率", render: (c) => num(c.pe_ttm) },
  { key: "pb", label: "PB", emptyNote: "没有市净率", render: (c) => num(c.pb, 2) },
  { key: "gross_margin", label: "毛利率", emptyNote: "没有毛利率", render: (c) => (c.gross_margin === null ? "—" : `${num(c.gross_margin)}%`) },
  { key: "roe", label: "ROE", emptyNote: "没有 ROE", render: (c) => (c.roe === null ? "—" : `${num(c.roe)}%`) },
  { key: "revenue_growth", label: "营收增速", emptyNote: "没有营收增速", render: (c) => pct(c.revenue_growth) },
  { key: "net_profit_growth", label: "净利增速", emptyNote: "没有净利增速", render: (c) => pct(c.net_profit_growth) },
  { key: "dividend_yield", label: "股息率", emptyNote: "没有股息率", render: (c) => pct(c.dividend_yield, 2) },
  { key: "change_60d", label: "60 日", emptyNote: "近 60 日涨跌要等同步任务攒够交易日", render: (c) => pct(c.change_60d) },
  { key: "ytd_change", label: "年内", emptyNote: "年内涨跌要等同步任务攒够交易日", render: (c) => pct(c.ytd_change) },
];

function NodeBlock({ node, columns, onOpenCompany }: { node: ChainCompareNode; columns: Column[]; onOpenCompany: (id: number) => void }) {
  return (
    <section className="chain-compare-node" aria-labelledby={`compare-node-${node.node_id}`}>
      <header className="chain-compare-node-head">
        <div>
          <small>{node.stage}</small>
          <strong id={`compare-node-${node.node_id}`}>{node.node}</strong>
          {node.what && <p>{node.what}</p>}
        </div>
        <dl className="chain-compare-stats">
          <div><dt>公司</dt><dd>{node.count}</dd></div>
          <div><dt>合计市值</dt><dd>{yi(node.market_cap_sum)}</dd></div>
          <div><dt>合计营收</dt><dd>{yi(node.revenue_sum)}</dd></div>
          <div><dt>合计净利</dt><dd>{yi(node.net_profit_sum)}</dd></div>
          <div><dt>PE 中位</dt><dd>{num(node.pe_median)}</dd></div>
          <div><dt>PB 中位</dt><dd>{num(node.pb_median, 2)}</dd></div>
          <div><dt>毛利中位</dt><dd>{node.gross_margin_median === null ? "—" : `${num(node.gross_margin_median)}%`}</dd></div>
          <div><dt>ROE 中位</dt><dd>{node.roe_median === null ? "—" : `${num(node.roe_median)}%`}</dd></div>
          <div><dt>环节市销率</dt><dd>{num(node.ps, 2)}</dd></div>
        </dl>
      </header>
      {/* 拥挤度:分子只是 A 股这一批,分母常是全球盘子——所以它不是估值倍数,
          是「这批公司被定价成要吃下这个市场的多少倍」。口径必须跟着一起显示,否则这个数没法读。 */}
      {node.crowding !== null && node.market_size_cny_yi !== null && (
        <p className="chain-compare-crowding">
          <strong>环节拥挤度 {node.crowding.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}×</strong>
          <span>
            这一环 A 股合计市值 {yi(node.market_cap_sum)} ÷ 市场盘子 {node.market_size_cny_yi.toLocaleString("zh-CN", { maximumFractionDigits: 0 })} 亿元
          </span>
          <em title={node.market_size_basis}>{node.market_size_basis}</em>
          {node.market_size_source_url && (
            <a href={node.market_size_source_url} target="_blank" rel="noreferrer">出处 <Link2 size={11} /></a>
          )}
        </p>
      )}
      {node.missing_quote > 0 && (
        <p className="chain-compare-warn">
          <TriangleAlert size={13} />
          这一环有 {node.missing_quote} 家取不到行情,上面的中位数只算在有数的 {node.count - node.missing_quote} 家上。
        </p>
      )}
      <div className="tablish chain-compare-table">
        <table>
          <thead>
            <tr>
              <th scope="col">公司</th>
              {columns.map((col) => <th scope="col" key={col.key}>{col.label}</th>)}
              <th scope="col">申万二级</th>
              <th scope="col">出处</th>
            </tr>
          </thead>
          <tbody>
            {node.companies.map((company) => (
              <tr key={`${node.node_id}-${company.company_id}`} className={company.price === null ? "is-muted" : undefined}>
                <th scope="row">
                  <button type="button" className="text-button" onClick={() => onOpenCompany(company.company_id)}>
                    {company.company}
                  </button>
                  <em>{company.symbol}</em>
                </th>
                {columns.map((col) => <td key={col.key}>{col.render(company)}</td>)}
                <td>{company.sw_level2 || company.sw_level1 || "—"}</td>
                <td>
                  {company.source_url
                    ? <a href={company.source_url} target="_blank" rel="noreferrer" aria-label={`${company.company} 挂在这一环的出处`}><Link2 size={12} /></a>
                    : <em>—</em>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function ChainCompareTable({ view, onOpenCompany }: { view: ChainCompareView; onOpenCompany: (id: number) => void }) {
  if (view.nodes.length === 0) {
    return (
      <p className="chain-compare-empty">
        这张底图上还没有标注公司。先在「编辑与标注」里把公司钉到环节上,这一屏才有东西可比。
      </p>
    );
  }
  const coverage = view.coverage || {};
  // 老接口没有 coverage 时(字段缺失)一律照常显示,不要把有数据的列误收起来
  const shown = COLUMNS.filter((col) => coverage[col.key] === undefined || coverage[col.key] > 0);
  const hidden = COLUMNS.filter((col) => coverage[col.key] === 0);
  return (
    <div className="chain-compare">
      <p className="chain-compare-lede">
        <strong>{view.theme}</strong> · {view.node_count} 个环节 · {view.company_count} 个公司位置。
        同一家公司出现在多个环节时会重复出现——它本来就同时在这几个市场里。
        行情与财务来自全市场底座(同步任务每 30 分钟刷新),不是实时逐笔。
        中位数回答「同一环里这家贵不贵」,合计营收与合计净利回答「这条链的利润落在哪一环」,
        拥挤度回答「这批公司被定价成要吃下这个市场的多少倍」——三个问题,三组数,不要混着读。
      </p>
      {hidden.length > 0 && (
        <p className="chain-compare-warn">
          <TriangleAlert size={13} />
          收起了 {hidden.map((col) => col.label).join("、")}:{hidden[0].emptyNote}
          {hidden.length > 1 ? " 等" : ""},这批公司一个都没有值。
        </p>
      )}
      {view.nodes.map((node) => <NodeBlock key={node.node_id} node={node} columns={shown} onOpenCompany={onOpenCompany} />)}
    </div>
  );
}
