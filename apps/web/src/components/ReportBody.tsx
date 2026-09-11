/**
 * 研究简报正文：把 [3] 这样的编号变成能点的引用。
 *
 * ## 为什么值得做
 *
 * 简报的全部可信度来自「每句话都挂着编号」这条规则——模型不许写没有编号支撑的
 * 句子。但编号只有在**能验证**的时候才起作用：原来 [3] 只是正文里的三个字符，
 * 引用清单在页面底部另起一块，想核对得自己数到第三条。数一次还行，
 * 一份简报十几个编号，没人会去数。**能验证但很费劲，等于不能验证。**
 *
 * 现在点一下就跳到那一条，并且带着原始公告链接——从"这句话是模型说的"
 * 到"这句话出自 2026-04-25 的这份年报"，中间只隔一次点击。
 *
 * ## 编号从哪来
 *
 * 后端在把资料送给模型之前就把序号定死了，回来照序号查表。
 * 不让模型自己编号，也不在前端重新 enumerate 一遍——**两处各编一次，
 * 只要中间筛掉过一条，[3] 就会指到另一条资料上，而这种错完全看不出来**：
 * 编号仍然在，指向的东西是错的。
 *
 * ## 找不到的编号
 *
 * 模型偶尔会写一个清单里没有的编号。这时不静默吞掉，也不装作能点——
 * 画成灰色并标注「清单里没有这一条」。一个指不到东西的引用是这份简报里
 * 最该被看见的缺陷，藏起来等于替它遮丑。
 */

import { useState } from "react";

import type { ResearchReport } from "../types";

type Citation = {
  ref?: number; label?: string; text?: string;
  kind?: string; evidence_id?: number | null; url?: string; occurred_at?: string;
};

const SECTIONS = [
  ["business", "这家公司在做什么"],
  ["changes", "最近发生了什么变化"],
  ["implications", "这些变化指向什么"],
] as const;

/** 把一行文字按 [3] / [1][4] 切开，编号部分渲染成角标。 */
function withCitations(line: string, onPick: (ref: number) => void, known: Set<number>) {
  const parts: React.ReactNode[] = [];
  const pattern = /\[(\d{1,3})\]/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(line)) !== null) {
    if (match.index > cursor) parts.push(line.slice(cursor, match.index));
    const ref = Number(match[1]);
    parts.push(
      known.has(ref)
        ? <button type="button" className="cite" key={`${match.index}-${ref}`}
                  onClick={() => onPick(ref)} title="看这条引用的出处">{ref}</button>
        : <span className="cite cite--missing" key={`${match.index}-${ref}`}
                title="清单里没有这一条">{ref}</span>,
    );
    cursor = match.index + match[0].length;
  }
  if (cursor < line.length) parts.push(line.slice(cursor));
  return parts;
}

export function ReportBody({ report }: { report: ResearchReport }) {
  const [picked, setPicked] = useState<number | null>(null);
  const citations = (report.citations ?? []) as Citation[];
  const known = new Set(citations.map((c) => c.ref).filter((r): r is number => typeof r === "number"));
  const current = picked === null ? null : citations.find((c) => c.ref === picked) ?? null;
  const structured = report.business.length + report.changes.length + report.implications.length > 0;

  return <>
    {structured
      ? SECTIONS.map(([key, title]) => report[key].length > 0 && (
          <section className="report-section" key={key}>
            <h5>{title}</h5>
            <ul>{report[key].map((line, index) => (
              <li key={index}>{withCitations(line, setPicked, known)}</li>
            ))}</ul>
          </section>
        ))
      // 老简报没有三节，只有一坨 body。原样显示，但编号照样可点。
      : <pre className="report-plain">{report.body.split("\n").map((line, index) => (
          <span key={index}>{withCitations(line, setPicked, known)}{"\n"}</span>
        ))}</pre>}

    {current && <div className="cite-card">
      <div className="cite-card-head">
        <span className="cite cite--open">{current.ref}</span>
        <strong>{current.label}</strong>
        <button className="text-button" onClick={() => setPicked(null)}>收起</button>
      </div>
      <p>{current.text}</p>
      {current.url
        ? <a href={current.url} target="_blank" rel="noreferrer">打开原始公告 ↗</a>
        : <em className="cite-nourl">这条是档案里的事件记录，没有外部链接。</em>}
    </div>}

    {citations.length > 0 && <details className="cite-all">
      <summary>全部引用（{citations.length} 条）</summary>
      <ol>
        {citations.map((item) => (
          <li key={item.ref} id={`cite-${item.ref}`}>
            <button type="button" className="text-button" onClick={() => setPicked(item.ref ?? null)}>
              {item.label}
            </button>
            <span>{item.text}</span>
          </li>
        ))}
      </ol>
    </details>}
  </>;
}
