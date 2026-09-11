/**
 * 深度研究报告的版式。
 *
 * ## 排版顺序 = 阅读顺序
 *
 * 结论卡 → 主题分布 → 分章正文 → 资料覆盖 → 还不知道的。
 * 结论卡放最前面：它是整份报告唯一保证被读到的部分。
 * 「还不知道的」放最后但**不折叠**——一份诚实说"这三件事查不到"的报告，
 * 比一份把三件事编圆了的有用得多，前者告诉你下一步该去查什么。
 *
 * ## 图表铁律（跟虾米跨境那套一致）
 *
 * - **长度只编码「样本内真实计数」**：主题条的长度是支持它的资料条数，
 *   绝不换算成百分比。三条资料提到一件事就是三条，不是"37% 的资料提到"——
 *   后者听起来像统计，其实是我们自己造出来的。
 * - **证据不足（少于 2 条）画成空心**，一眼看出这条结论只有一个来源撑着。
 * - **数据缺失时组件返回 null**，页面回落到纯文字，不显示空图框。
 *
 * ## 颜色
 *
 * 主题方向用发散对（#d03b3b 朱红 = 负面 / #1baf7a 青绿 = 正面），
 * 与方法体检矩阵同一套，跑过 validate_palette。
 * **这里的红绿是「对经营而言」，不是涨跌**——所以负面用红：
 * 在这一屏里红始终代表"要当心的一侧"，跟行情那一屏的红涨绿跌不冲突，
 * 因为两者不会同时出现在同一张图上。
 *
 * 资料分级用单色相明度分级（一手最深 → 其他最浅）：那是**可信度的顺序**，
 * 有序的东西用明度不用色相，色觉障碍与灰度打印下照样读得出先后。
 */

import { useState } from "react";

import type { ResearchReport } from "../types";

const POSITIVE = "#1baf7a";
const NEGATIVE = "#d03b3b";
const NEUTRAL = "#8d99a4";

// 可信度从高到低，明度递增（深 = 更可信）。实测单调：0.42 → 0.50 → 0.62 → 0.72 → 0.82
const KIND_STEPS: Record<string, string> = {
  一手: "#1a4f7a", 本地已归档: "#2a78d6", 媒体: "#6ba3e0", 研报: "#9dc0e8", 观点: "#c3d8ee", 其他: "#dde6ef",
};
const KIND_ORDER = ["一手", "本地已归档", "媒体", "研报", "观点", "其他"];

type Source = { ref?: number; kind?: string; title?: string; url?: string;
                published?: string; snippet?: string };

/** 把一行文字里的 [3] 变成可点角标。编号由后端定死，前端不重新编。 */
function withRefs(line: string, known: Set<number>, onPick: (ref: number) => void) {
  const parts: React.ReactNode[] = [];
  const pattern = /\[(\d{1,3})\]/g;
  let cursor = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(line)) !== null) {
    if (match.index > cursor) parts.push(line.slice(cursor, match.index));
    const ref = Number(match[1]);
    parts.push(known.has(ref)
      ? <button type="button" className="cite" key={`${match.index}`}
                onClick={() => onPick(ref)}>{ref}</button>
      : <span className="cite cite--missing" key={`${match.index}`} title="清单里没有这一条">{ref}</span>);
    cursor = match.index + match[0].length;
  }
  if (cursor < line.length) parts.push(line.slice(cursor));
  return parts;
}

function Themes({ themes }: { themes: NonNullable<ResearchReport["themes"]> }) {
  const rows = themes.filter((t) => t.name);
  if (rows.length === 0) return null;
  // 长度是**真实资料条数**，不换算成百分比
  const max = Math.max(...rows.map((t) => (t.refs?.length ?? 0)), 1);

  return (
    <figure className="dr-fig">
      <figcaption>资料在讨论什么<span>条的长度 = 提到它的资料条数</span></figcaption>
      <div className="dr-themes">
        {rows.map((theme) => {
          const count = theme.refs?.length ?? 0;
          const color = theme.direction === "正面" ? POSITIVE
                      : theme.direction === "负面" ? NEGATIVE : NEUTRAL;
          return (
            <div className="dr-theme" key={theme.name}>
              <span className="dr-theme-name">{theme.name}</span>
              <div className="dr-theme-track">
                {/* 少于两条资料撑着的，画成空心 —— 一眼看出它只有一个来源 */}
                <i style={{
                  width: `${(count / max) * 100}%`,
                  background: count >= 2 ? color : "transparent",
                  border: count >= 2 ? "none" : `1.5px solid ${color}`,
                }} />
              </div>
              <span className="dr-theme-meta" style={{ color }}>
                {theme.direction} · {count} 条
              </span>
            </div>
          );
        })}
      </div>
      <p className="chart-note">
        方向指的是<strong>对这家公司的经营而言</strong>，不是对股价。
        空心表示只有一条资料提到，分量最轻。
      </p>
    </figure>
  );
}

function Coverage({ sources }: { sources: Source[] }) {
  if (sources.length === 0) return null;
  const counts = new Map<string, number>();
  for (const s of sources) counts.set(s.kind ?? "其他", (counts.get(s.kind ?? "其他") ?? 0) + 1);
  // **名单外的档位不能凭空消失。** 原来这里是 KIND_ORDER.filter(...)，
  // 后端哪天多一个档（比如把百科单列），它就不进这条覆盖率条 ——
  // 而这条的全部意义就是"一手占多少"，少算一块等于给了个偏高的数，
  // 且百分比加起来不到 100 也没人会注意。认不出的排最后，照旧显示。
  const known = KIND_ORDER.filter((k) => counts.has(k));
  const extra = [...counts.keys()].filter((k) => !KIND_ORDER.includes(k)).sort();
  const rows = [...known, ...extra].map((k) => [k, counts.get(k)!] as const);
  if (rows.length === 0) return null;
  const total = sources.length;

  return (
    <figure className="dr-fig">
      <figcaption>这份报告靠什么写的<span>共 {total} 条</span></figcaption>
      {/* 一条堆叠比例条：要看的是"一手占多少"，那是可信度的第一判据 */}
      <div className="dr-cov" role="img"
           aria-label={rows.map(([k, n]) => `${k} ${n} 条`).join("，")}>
        {rows.map(([kind, n]) => (
          <i key={kind} style={{ flexGrow: n, background: KIND_STEPS[kind] ?? "#dde6ef" }}
             title={`${kind} ${n} 条`} />
        ))}
      </div>
      <div className="dr-cov-legend">
        {rows.map(([kind, n]) => (
          <span key={kind}><i style={{ background: KIND_STEPS[kind] ?? "#dde6ef" }} />{kind} {n}</span>
        ))}
      </div>
      <p className="chart-note">
        颜色越深越接近一手。<strong>一手</strong>（交易所、监管、公司公告）可以当事实；
        <strong>媒体</strong>是二手转述；<strong>研报与观点</strong>只说明市场在这样讨论，不是事实。
      </p>
    </figure>
  );
}

export function DeepReport({ report }: { report: ResearchReport }) {
  const [picked, setPicked] = useState<number | null>(null);
  const sources = (report.sources ?? []) as Source[];
  const known = new Set(sources.map((s) => s.ref).filter((r): r is number => typeof r === "number"));
  const current = picked === null ? null : sources.find((s) => s.ref === picked) ?? null;

  return <>
    {/* 结论卡最先 —— 它是整份报告唯一保证被读到的部分 */}
    {report.cards.length > 0 && <div className="dr-cards">
      {report.cards.map((card) => (
        <article className="dr-card" key={card.title}>
          <h5>{card.title}</h5>
          <p>{withRefs(card.point ?? "", known, setPicked)}</p>
        </article>
      ))}
    </div>}

    <div className="dr-figs">
      <Themes themes={report.themes ?? []} />
      <Coverage sources={sources} />
    </div>

    {report.sections.map((section) => (
      <section className="report-section" key={section.title}>
        <h5>{section.title}</h5>
        <ul>{(section.lines ?? []).map((line, index) => (
          <li key={index}>{withRefs(line, known, setPicked)}</li>
        ))}</ul>
      </section>
    ))}

    {current && <div className="cite-card">
      <div className="cite-card-head">
        <span className="cite cite--open">{current.ref}</span>
        <strong>{current.kind} · {current.title}</strong>
        <button className="text-button" onClick={() => setPicked(null)}>收起</button>
      </div>
      <p>{current.snippet}</p>
      {current.url
        ? <a href={current.url} target="_blank" rel="noreferrer">打开原文 ↗</a>
        : <em className="cite-nourl">本地归档的证据，没有外部链接。</em>}
    </div>}

    {/* 不折叠：一份诚实说"这三件事查不到"的报告，比把它们编圆了的有用得多 */}
    {report.unknowns.length > 0 && <div className="dr-unknowns">
      <h5>还不知道的</h5>
      <ul>{report.unknowns.map((u) => <li key={u}>{u}</li>)}</ul>
    </div>}

    {report.queries.length > 0 && <details className="cite-all">
      <summary>搜了这几个问题（{report.queries.length} 个）· 全部资料 {sources.length} 条</summary>
      <ul className="dr-queries">{report.queries.map((q) => <li key={q}>{q}</li>)}</ul>
      <ol>
        {sources.map((s) => (
          <li key={s.ref}>
            <button type="button" className="text-button" onClick={() => setPicked(s.ref ?? null)}>
              [{s.ref}] {s.kind} · {s.title}
            </button>
          </li>
        ))}
      </ol>
    </details>}
  </>;
}
