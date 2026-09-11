/**
 * 组合共同风险：我以为的分散，是不是同一个赌注下了五次。
 *
 * ## 为什么要单独一块
 *
 * 持仓列表会告诉你「6 只票，最大一只 22%」，于是你觉得自己是分散的。
 * 但分散不是由**只数**决定的，是由**它们会不会同时出事**决定的。
 * 券商的持仓页只按行业画一张饼，而行业分类恰恰是重叠里最不值钱的那种——
 * 它是公开的，你自己也知道。
 *
 * ## 权重条的宽度是真的仓位，不是排名
 *
 * 「这几只占我多少」是这一页唯一有用的那个数，所以它必须是长度、
 * 不是一个躲在角落的百分比数字。**算不出权重时条不画**——
 * 画一根等长的条等于说"它们一样重"，而那正好是最容易骗人的地方。
 *
 * ## 不用红色
 *
 * 集中不等于做错了，真懂的人本来就该集中。红色会把一个事实变成一句指责，
 * 而被指责的机制会被绕开。所以这里只有中性色，轻重靠条的长短表达。
 */

import { useEffect, useState } from "react";
import { Boundary } from "./Boundary";

import { getPortfolioCommonRisk, type CommonRiskGroup, type CommonRiskView } from "../api";

function rich(text: string) {
  return text.split(/\*\*/).map((part, index) =>
    index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>);
}

const KIND_LABEL: Record<string, string> = {
  industry: "行业", segment: "分部", chain: "上下游",
  valuation: "估值", 市值: "市值", trend: "位置", counter: "认错条件",
};

function Group({ group, index }: { group: CommonRiskGroup; index: number }) {
  const hasWeights = group.weight !== null && group.weight > 0;
  return <details className="cr-group">
    <summary className="cr-group-summary">
      <span className="cr-group-index">{String(index + 1).padStart(2, "0")}</span>
      <span className="cr-kind">{KIND_LABEL[group.kind] ?? group.kind}</span>
      <b>{group.label}</b>
      <em>{group.member_count} 只{group.weight !== null ? ` · ${group.weight}% 仓位` : ""}</em>
      <span className="cr-group-arrow" aria-hidden="true">＋</span>
    </summary>
    <div className="cr-group-body">
      {hasWeights && <div className="cr-member-stack" aria-label={`${group.label}覆盖仓位 ${group.weight}%`}>
        {group.members.map((member) => <span key={member.symbol} style={{ width: `${Math.max(2, ((member.weight ?? 0) / (group.weight ?? 1)) * 100)}%` }} />)}
      </div>}
      <ul className="cr-members">
        {group.members.map((m) => <li key={m.symbol}>
          <b>{m.name}</b> <span className="cr-symbol">{m.symbol}</span>
          {m.weight !== null && <span className="cr-weight">{m.weight}%</span>}
          {m.detail && <em>{m.detail}</em>}
        </li>)}
      </ul>
      <div className="cr-reading-grid">
        <div><span>事实</span><p className="cr-evidence">{rich(group.evidence)}</p></div>
        <div><span>要问自己</span><p className="cr-question">{rich(group.question)}</p></div>
      </div>
      {group.confidence && <p className="cr-caveat">{rich(group.confidence)}</p>}
    </div>
  </details>;
}

export function CommonRisk({ portfolioId, onOpenCompany }: {
  portfolioId: number | null;
  /** 只有一只持仓时，要能一键跳到那家公司去写／看认错条件。 */
  onOpenCompany?: (companyId: number) => void;
}) {
  const [view, setView] = useState<CommonRiskView | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (portfolioId === null) { setView(null); return; }
    let live = true;
    setView(null); setError("");
    getPortfolioCommonRisk(portfolioId)
      .then((next) => { if (live) setView(next); })
      .catch((caught) => { if (live) setError(caught instanceof Error ? caught.message : "读取失败"); });
    return () => { live = false; };
  }, [portfolioId]);

  if (portfolioId === null) return null;
  if (error) return <p className="form-error">{error}</p>;
  if (!view) return <div className="empty-state">正在查这些持仓会不会同时出事…</div>;

  const maxWeight = view.groups.reduce((max, group) => Math.max(max, group.weight ?? 0), 0);
  return <div className="common-risk">
    <div className="cr-overview">
      <div className="cr-overview-lead">
        <span className="eyebrow">共同风险</span>
        <h3>{view.groups.length > 0 ? `${view.groups.length} 处重合` : "暂未发现重合"}</h3>
        <p>{view.groups.length > 0 ? "先看覆盖仓位，再点开一组核对它们共用的事实。" : "当前持仓没有达到共同风险的展示条件。"}</p>
      </div>
      <div className="cr-overview-stats">
        <div><strong>{view.position_count}</strong><span>只持仓</span></div>
        <div><strong>{maxWeight > 0 ? `${maxWeight}%` : "—"}</strong><span>最大覆盖仓位</span></div>
        <div><strong>{view.hidden > 0 ? `+${view.hidden}` : "0"}</strong><span>低权重未列</span></div>
      </div>
    </div>
    {/* **满仓单只是散户最典型的错误，而这一页原来对它完全沉默**
        （门槛是 3 只）。现在它说话了，而且直接把人送到唯一要紧的那件事上：
        这家公司的认错条件。 */}
    {view.single && view.single.company_id !== null && onOpenCompany && <p className="cr-single">
      <button className="text-button" onClick={() => onOpenCompany(view.single!.company_id!)}>
        去看 {view.single.name} 的认错条件 →
      </button>
    </p>}
    {view.groups.length > 0 && <div className="cr-map-head"><span>按覆盖仓位排序</span><em>点击一行查看证据</em></div>}
    {view.groups.map((group, index) => <Group key={`${group.kind}-${group.label}-${index}`} group={group} index={index} />)}
    <details className="cr-boundary-details">
      <summary>查看计算边界</summary>
      {view.note && <p>{rich(view.note)}</p>}
      <Boundary text={view.boundary} label="这些数从哪来、它不会做什么" />
    </details>
  </div>;
}
