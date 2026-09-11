/**
 * 决策归因：我写下的判断，后来怎么样了。
 *
 * ## 闭环的第三环
 *
 * 写下判断 → 世界变了没有 → **我错在哪**。没有第三环，什么都不会复利：
 * 每一次决策都是从零开始的。
 *
 * ## 这一版只报机械可验证的事实
 *
 * 「我总为成长付太高的价」这类倾向需要几十次决策才谈得上，而且判定本身
 * 就是一次判断——很容易变成一句听着很像回事、其实是编的话。
 * **一份编出来的归因比没有归因更糟：你会照着它改行为。**
 *
 * 所以这里只回答三件不需要判断的事：写下时是什么价、认错条件触发过没有、
 * 触发之后你做了什么。第三条是全部的重点——前两条任何行情软件都能给你。
 *
 * ## 「触发了但没动」不着色成红色
 *
 * 它不是错误。**没动也可能完全正确**（你重新想过，认为那条件写得太紧）。
 * 用红色会把它变成一句指责，而被指责的机制会被绕开。
 * 所以四种状态用同一套中性色，只在文字上分开。
 */

import { useEffect, useState } from "react";
import { Boundary } from "./Boundary";

import { getAttribution, type AttributionView } from "../api";

function rich(text: string) {
  // 按空行/换行分段：门槛提示是两句话，挤成一行读起来像一句。
  return text.split("\n").filter(Boolean).map((line, block) => (
    <p key={block}>
      {line.split(/\*\*/).map((part, index) =>
        index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>)}
    </p>
  ));
}

export function Attribution({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  const [view, setView] = useState<AttributionView | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    getAttribution().then((next) => { if (live) setView(next); })
      .catch((caught) => { if (live) setError(caught instanceof Error ? caught.message : String(caught)); });
    return () => { live = false; };
  }, []);

  if (error) return <p className="form-error">{error}</p>;
  if (!view) return <div className="empty-state">正在读取…</div>;

  return <>
    <section className="page-intro archive-intro">
      <div>
        <span className="section-kicker">ATTRIBUTION</span>
        <h1>我写下的判断，后来怎么样了</h1>
        <p>闭环的第三环。<strong>只数机械可验证的事实</strong>——写下时的价、现在的价、
           认错条件触发过没有、触发之后你动没动。</p>
      </div>
      <div className="local-stamp"><span>THESES</span><strong>{view.total} 条</strong></div>
    </section>

    <section className="panel">
      <p className="at-headline">{rich(view.headline)}</p>
      {view.question && <p className="at-question">{rich(view.question)}</p>}
      {/* **门槛没到时给进度，不是给一句"不够"。**
          原来这里是「只有 4 条，谈不上规律」——读完没有下文，也看不出还差多远。
          进度条把它变成一个能往前推的东西；而下面那张表里逐条的事实
          （写下时什么价、认错条件触发过没有）一条样本都不需要，现在就成立。 */}
      {view.progress && !view.enough && (
        <div className="at-progress">
          <div className="at-progress-bar" role="img"
               aria-label={`已写 ${view.progress.have} 条，到 ${view.progress.need} 条开始看倾向`}>
            <i style={{ width: `${Math.min(100, view.progress.have / view.progress.need * 100)}%` }} />
          </div>
          <span>{view.progress.have} / {view.progress.need}</span>
        </div>
      )}
      {view.note && <div className="at-note">{rich(view.note)}</div>}

      {view.rows.length === 0
        ? <div className="empty-state">还没有判断。顶栏的「写下一个判断」三十秒就能写一条。</div>
        : <div className="at-table-wrap">
            <table className="at-table">
              <thead><tr>
                <th>公司</th><th>写下</th><th>写下时</th><th>现在</th><th>变动</th>
                <th>认错条件</th><th>状态</th>
              </tr></thead>
              <tbody>
                {view.rows.map((row) => (
                  <tr key={row.thesis_id}>
                    <th scope="row">
                      <button className="text-button" onClick={() => onOpenCompany(row.company_id)}>
                        {row.company_name}
                      </button>
                    </th>
                    <td className="at-num">{row.written_at?.slice(0, 10)}</td>
                    <td className="at-num">{row.price_at_write?.toFixed(2) ?? "—"}</td>
                    <td className="at-num">{row.price_now?.toFixed(2) ?? "—"}</td>
                    <td className="at-num">
                      {row.price_move === null ? "—"
                        : `${row.price_move > 0 ? "+" : ""}${row.price_move.toFixed(1)}%`}
                    </td>
                    <td className="at-claim">{row.counter_condition || <em>没写</em>}</td>
                    {/* **不着红色。** 「没动」不是错误，用颜色指责会让人绕开这一页。 */}
                    <td className="at-state">{row.state}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>}

      <Boundary text={view.boundary} />
    </section>
  </>;
}
