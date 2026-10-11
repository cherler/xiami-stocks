import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { getStockResponse, setResponseWatch, type StockResponse } from "../api";
import "./StockResponseReport.css";

const Rally = lazy(() => import("./RallyType").then(m => ({ default: m.RallyType })));
const Swing = lazy(() => import("./SwingLab").then(m => ({ default: m.SwingLab })));
const percent = (n: number) => `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;

function PriceChart({ report }: { report: StockResponse }) {
  const points = report.prices.chart;
  if (points.length < 2) return null;
  const values = points.flatMap(p => p.ma60 === null ? [p.close] : [p.close, p.ma60]);
  const bottom = Math.min(...values);
  const top = Math.max(...values);
  const range = Math.max(top - bottom, top * .01);
  const line = points.map((p, i) => `${36 + i / (points.length - 1) * 698},${160 - (p.close - bottom) / range * 130}`).join(" ");
  const average = points.map((p, i) => p.ma60 === null ? "" : `${36 + i / (points.length - 1) * 698},${160 - (p.ma60 - bottom) / range * 130}`).filter(Boolean).join(" ");
  return <figure className="sr-chart">
    <figcaption>近 {points.length} 个交易日 · 前复权收盘价 <span>实线：收盘价 · 虚线：60 日均线</span></figcaption>
    <svg viewBox="0 0 780 196" role="img" aria-label={`${report.company.name}从 ${points[0].date} 到 ${points.at(-1)?.date} 的收盘走势，最低 ${bottom.toFixed(2)}，最高 ${top.toFixed(2)}`}>
      <line x1="36" x2="734" y1="160" y2="160" className="sr-chart-axis" />
      <polyline points={line} fill="none" className="sr-chart-line" />
      {average && <polyline points={average} fill="none" className="sr-chart-average" />}
      <text x="740" y="34">{top.toFixed(1)}</text><text x="740" y="164">{bottom.toFixed(1)}</text>
      <text x="36" y="187">{points[0].date}</text><text x="734" y="187" textAnchor="end">{points.at(-1)?.date}</text>
    </svg>
  </figure>;
}

export function StockResponseReport({ companyId, onBack, onOpenCompany, onOpenPlan, renderReview }: {
  companyId: number; onBack: () => void; onOpenCompany: (id: number, tab?: string) => void;
  onOpenPlan: () => void; renderReview: (id: number) => ReactNode;
}) {
  const [report, setReport] = useState<StockResponse | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<"rally" | "swing" | "review" | null>(null);
  useEffect(() => {
    let live = true;
    setError("");
    getStockResponse(companyId).then(result => { if (live) setReport(result); })
      .catch(e => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [companyId, revision]);
  async function toggleWatch() {
    if (!report) return;
    setBusy(true); setError("");
    try {
      const result = await setResponseWatch(companyId, !report.watching);
      setReport(current => current && { ...current, watching: result.watching });
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  return <article className="sr-report">
    <div className="sr-toolbar"><button className="text-button" onClick={onBack}>← 我的跟踪</button>
      <button className="text-button" onClick={() => setRevision(v => v + 1)}>重新读取</button></div>
    {error && <p role="alert" className="sr-message">{error}</p>}
    {!report && !error && <p role="status">正在整理已有行情和研究…</p>}
    {report && <>
      <header className="sr-header"><div><p className="sr-eyebrow">个股应对报告 · {report.horizon}</p>
        <h1>{report.company.name}<span>{report.company.symbol}</span></h1></div>
        <button className="text-button" onClick={() => onOpenCompany(companyId)}>公司资料 ↗</button></header>
      <section className="sr-verdict" aria-label="当前应对">
        <p className="sr-meta">{report.regime_label} · 行情截至 {report.prices.as_of || "待补"}</p>
        <h2>{report.action}</h2>
        <p className="sr-position">{report.position_note}{report.position?.weight_percent != null ? ` · 账本仓位 ${report.position.weight_percent}%` : ""}</p>
        {!report.position && <p className="sr-alternative">如果你已持有：{report.held_action}</p>}
        <ul className="sr-reasons">{report.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>
        <div className="sr-change"><strong>结论变化</strong><span>{report.change_note || (report.previous_action
          ? `${report.previous_at?.slice(0, 10)}：${report.previous_action} → 现在：${report.action}`
          : "首次记录当前结论；后续与这次比较。")}</span></div>
      </section>
      <section className="sr-next" aria-label="下一步关注">
        <div><h2>接下来，只盯这些</h2><ul>{report.conditions.map(item => <li key={item}>{item}</li>)}</ul></div>
        <div className="sr-watch"><button className="page-action" disabled={busy} aria-pressed={report.watching}
          onClick={() => void toggleWatch()}>{busy ? "正在保存…" : report.watching ? "已关注 · 点击暂停" : "结论变了提醒我"}</button>
          <p>{report.watching ? report.watch_running ? "已加入现有助手的检查队列；接收渠道沿用你的助手设置。" : "已保存关注；后台自动检查尚未开启。"
            : "应对或复核状态变了才提醒，普通涨跌不推送。"}</p></div>
      </section>
      <PriceChart report={report} />
      <section className="sr-strategies"><h2>多操作，过去真的更好吗？</h2>
        <p>同一只股票、同一段历史、同样的初始资金。持有不动是比较基准。</p>
        {report.prices.strategies.length > 0 && <div className="sr-table-scroll"><table><caption>
          {report.prices.comparison_from} — {report.prices.comparison_to} · 扣除模拟交易成本</caption>
          <thead><tr><th>固定做法</th><th>区间收益</th><th>比持有多赚</th><th>最大回撤</th><th>交易次数</th></tr></thead>
          <tbody>{report.prices.strategies.map(s => <tr key={s.key}><th scope="row">{s.label}</th><td>{percent(s.return_pct)}</td>
            <td>{s.key === "hold" ? "基准" : `${s.excess_pct > 0 ? "+" : ""}${s.excess_pct.toFixed(1)} 个百分点`}</td>
            <td>{percent(s.drawdown_pct)}</td><td>{s.trades}</td></tr>)}</tbody></table></div>}
        <p className="sr-meta">{report.prices.comparison_note || report.prices.note}</p>
        <details className="sr-details"><summary>展开规则与分段检验</summary>
          <p>固定三种规则：第一天买入持有；每隔 20 个交易日投入约三分之一；上升趋势配置 100%、方向未明 50%、下降趋势 0%。这些是假设仓位，不是给你的仓位建议。</p>
          <p>中期信号使用 20 / 60 日均线与 2% 缓冲，均线与价格同向才判趋势。当天收盘生成信号，下一交易日开盘执行；不做日内买卖。</p>
          <p>每段用 10 万元重新起算，现金不计息。买入成本约 0.13%，卖出约 0.18%，含单边 0.10% 滑点及最低 5 元佣金；期末按收盘计价，不假设卖出。前复权比例仓位模拟，不复现整手、分红到账和真实成交。极端跳空及一字板跳过成交。</p>
          <p>以下是按时间顺序分段的历史检验，没有调参或挑出“最优策略”，也不是未来胜率。</p>
          {report.prices.strategies.filter(s => s.key !== "hold").map(s => <div className="sr-blocks" key={s.key}>
            <strong>{s.label} · {s.blocks.length} 段中，{s.better_blocks} 段超过持有</strong>
            <ul>{s.blocks.map(b => <li key={b.from}>{b.from} — {b.to}：{b.excess_pct > 0 ? "+" : ""}{b.excess_pct.toFixed(1)} 个百分点</li>)}</ul>
            <p>跳过 {s.skipped_days} 天成交；模拟总成本 {s.cost.toFixed(0)} 元。</p></div>)}
        </details>
      </section>
      <section className="sr-original"><h2>你的原判断与计划</h2>
        <p>{report.thesis?.claim || report.plan_note || "还没有保存投资判断，可以让助手帮你记。"}</p>
        {report.band_note && <p className="sr-meta">{report.band_note}</p>}
        <div className="sr-links"><button className="text-button" onClick={onOpenPlan}>查看或调整计划</button>
          <button className="text-button" onClick={() => onOpenCompany(companyId, "research")}>原判断与证据</button></div></section>
      <details className="sr-details"><summary>需要深挖时，再打开工具{report.reviews.length ? ` · ${report.reviews.length} 条判断待复核` : ""}</summary>
        <div className="sr-links">{([['rally', '这段涨跌的线索'], ['swing', '做 T 实验'], ['review', '复核我的判断']] as const).map(([key, label]) =>
          <button className="text-button" key={key} aria-pressed={detail === key} onClick={() => setDetail(detail === key ? null : key)}>{label}</button>)}</div>
        <Suspense fallback={<p>正在打开…</p>}>
          {detail === "rally" && <Rally initialCompanyId={companyId} onOpenCompany={onOpenCompany} />}
          {detail === "swing" && <Swing initialCompanyId={companyId} onOpenCompany={onOpenCompany} />}
          {detail === "review" && renderReview(companyId)}
        </Suspense>
      </details>
      <p className="sr-meta sr-end">这是已有数据生成的应对规则，不预测目标价。报告自动读取新数据，不修改原判断或代你交易。</p>
    </>}
  </article>;
}
