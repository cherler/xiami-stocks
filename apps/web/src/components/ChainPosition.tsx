/**
 * 产业链位置：这门生意被谁卡着脖子。
 *
 * ## 为什么这一块要摆在产业链图上面
 *
 * 下面那张图是模型凭世界知识画的四个方框。实测中国平安那张，上游七条里
 * 三条是同一件事（「再保险人」「再保险公司」「再保险公司」，其中两条字面完全相同），
 * 下游是「个人客户」「个人投保人」「个人保险客户」——三种说法一个意思，
 * 而且都不是产业链节点，是空词。
 *
 * 而「产业链位置」这件事，年报里有确定的答案，是**强制披露项**：
 * 前五名客户占销售总额多少、前五名供应商占采购总额多少。
 *
 *     寒武纪  88.66%   ← 丢一个客户就伤筋动骨
 *     茅台    10.10%   ← 谁都卡不住它
 *
 * **一个数比整张示意图有用得多**，而且能点回年报原文核对。
 *
 * ## 两根条，长度就是比例
 *
 * 「88.66%」和「10.10%」的差别要能一眼看出来，所以画成条——
 * 数字并排放着需要人自己做减法，而做减法这件事人在扫读时不会做。
 *
 * ## 不打分，不给颜色警告
 *
 * 集中不等于差：给苹果供货的公司客户集中度极高，那是好生意还是坏生意，
 * 取决于它有没有被替代的可能。用红色会把一个事实变成一句指责，
 * 而被指责的机制会被绕开——跟组合共同风险那一页同一条规矩。
 */

import { useEffect, useState } from "react";
import { Boundary } from "./Boundary";

import { getChainPosition, type ChainPosition as ChainPositionView } from "../api";
import { Source } from "./Source";

function rich(text: string) {
  return text.split("\n\n").map((paragraph, block) =>
    <p key={block}>{paragraph.split(/\*\*/).map((part, index) =>
      index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>)}</p>);
}

function Bar({ label, hint, ratio, at, href }: {
  label: string; hint: string; ratio: number | null; at?: string; href?: string | null;
}) {
  if (ratio === null) return null;
  return <div className="cpos-metric">
    <div className="cpos-metric-head">
      <span>{label}</span>
      {/* **出处跟数字同行。** 这个产品跟别的软件的区别就在这——
          而原来它折在下面的 details 里，头顶压着三行解释。 */}
      <b>{ratio}% <Source kind="年报" at={at} href={href} /></b>
    </div>
    {/* 长度就是比例。数字并排放着要人自己做减法，而扫读时没人会做。 */}
    <div className="cpos-bar" aria-hidden="true">
      <span style={{ width: `${Math.min(100, Math.max(0, ratio))}%` }} />
    </div>
    <em>{hint}</em>
  </div>;
}

export function ChainPosition({ companyId }: { companyId: number }) {
  const [view, setView] = useState<ChainPositionView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    setView(null); setError("");
    getChainPosition(companyId)
      .then((next) => { if (live) setView(next); })
      .catch((caught) => { if (live) setError(caught instanceof Error ? caught.message : "读取失败"); });
    return () => { live = false; };
  }, [companyId]);

  async function refresh() {
    setBusy(true); setError("");
    try { setView(await getChainPosition(companyId, true)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "读取失败"); }
    finally { setBusy(false); }
  }

  if (error) return <p className="form-error">{error}</p>;
  if (!view) return <div className="empty-state">正在读年报里的客户与供应商集中度…</div>;

  return <div className="chain-position">
    {view.available ? <>
      <p className="cpos-reading">{rich(view.reading)}</p>
      <div className="cpos-metrics">
        <Bar label="前五大客户占销售总额" ratio={view.customer_ratio}
             at={view.report_date?.slice(0, 4)} href={view.source_url}
             hint="这个数越高，下游越集中——收入捏在越少的人手里" />
        <Bar label="前五大供应商占采购总额" ratio={view.supplier_ratio}
             at={view.report_date?.slice(0, 4)} href={view.source_url}
             hint="这个数越高，上游越集中——成本端越受制于人" />
      </div>
      {view.top.length > 0 && <ul className="cpos-top">
        {view.top.map((item, index) => <li key={index}>
          <span>{item.name}</span><b>{item.ratio}%</b>
        </li>)}
      </ul>}
      {/* **出处摆出来。** 这一页跟下面那张图的全部区别就在这里：
          这段字是从年报里一字不差抄出来的，点开年报能找到。 */}
      {view.excerpt && <details className="cpos-source">
        <summary>
          原文出处：{view.report_title || "年度报告"}
          {view.report_date ? `（${view.report_date}）` : ""}
          {view.source_url && <> · <a href={view.source_url} target="_blank" rel="noreferrer">打开年报</a></>}
        </summary>
        <pre>{view.excerpt}</pre>
      </details>}
    </> : <div className="empty-state">
      {/* **原因只说这一次真正的那个。**
          原来这里无条件跟着一句「银行与保险不适用这项披露——不是数据缺失」，
          而这次的原因是「这条公告没有巨潮的编号，拼不出正文地址」——
          两句话摆在一起互相矛盾，读的人不知道该信哪个。
          那句解释只在真的是银行保险时才成立，所以让它跟着 note 走。 */}
      <p><strong>{view.note}</strong></p>
      <button className="text-button" type="button" disabled={busy}
        onClick={() => void refresh()}>{busy ? "正在重读…" : "重新读一次年报"}</button>
    </div>}
    <Boundary text={view.boundary} />
  </div>;
}
