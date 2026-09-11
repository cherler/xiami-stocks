/**
 * 证据方向轴：写下判断之后，事实往哪边走。
 *
 * ## 为什么是发散点轴，不是累计折线
 *
 * 第一版想画"累计（支持−削弱）"的折线，它确实一眼能看出净方向。但那条线
 * **把每件事当成等重的 1 来加**——一次分红实施和一次董事辞任加起来正好抵消，
 * 而这个抵消是算出来的，不是真的。折线画出来又特别有说服力，
 * 人会盯着它的斜率读"趋势"，而斜率的全部来源只是"这段时间公告条数多"。
 *
 * 所以改成发散点轴：支持在上、削弱在下、中性贴着轴。
 * 密疏、方向、时间都看得见，**但不做任何加减**。要看总数就看上面那行数字。
 *
 * ## 判断写下的那天要画出来
 *
 * 这根轴唯一要回答的问题是"我写下判断**之后**发生了什么"。不标出那个时点，
 * 左边那些历史证据会跟后来的混在一起读——而它们的意义完全不同：
 * 之前的是你当初的依据，之后的才是对判断的检验。
 *
 * ## 颜色
 *
 * 青绿 ↔ 朱红的发散对（#1baf7a / #d03b3b），跟方法体检矩阵同一套：
 * 跑过 validate_palette，正常视力 ΔE 31.9、色觉障碍最差 9.9。
 * 跟着 A 股惯例走——同一屏里红不能一会儿是好一会儿是坏。
 * 上下位置本身也编码了方向，颜色不是唯一线索。
 */

import { useMemo, useState } from "react";

import type { EvidenceDirectionView } from "../api";

const SUPPORT = "#1baf7a";
const COUNTER = "#d03b3b";

const TONE: Record<string, { color: string; row: number; label: string }> = {
  support: { color: SUPPORT, row: 0, label: "支持" },
  counter: { color: COUNTER, row: 2, label: "削弱" },
  neutral: { color: "#a9b4bd", row: 1, label: "中性" },
};

export function EvidenceAxis({ data }: { data: EvidenceDirectionView }) {
  const [picked, setPicked] = useState<number | null>(null);

  const layout = useMemo(() => {
    if (data.events.length === 0) return null;
    const days = data.events.map((e) => Date.parse(e.date)).filter((n) => !Number.isNaN(n));
    const from = Math.min(...days);
    const to = Math.max(...days);
    const span = to - from || 1;
    const at = (date: string) => ((Date.parse(date) - from) / span) * 100;
    return { at, from, to };
  }, [data]);

  if (!layout) {
    return <div className="empty-state">
      还没有判过方向的证据。点上面的按钮跑一次，才知道事实是在往你的判断那边走还是反着走。
    </div>;
  }

  const counts = data.events.reduce<Record<string, number>>((acc, e) => {
    acc[e.polarity] = (acc[e.polarity] ?? 0) + 1;
    return acc;
  }, {});
  const opened = data.events.find((e) => e.id === picked) ?? null;
  const marker = data.theses[0]?.date;

  return <>
    <div className="axis-summary">
      <span><i style={{ background: SUPPORT }} />支持 <strong>{counts.support ?? 0}</strong></span>
      <span><i style={{ background: COUNTER }} />削弱 <strong>{counts.counter ?? 0}</strong></span>
      <span><i style={{ background: TONE.neutral.color }} />中性 <strong>{counts.neutral ?? 0}</strong></span>
      <em>共 {data.events.length} 件事，来自 {data.total_documents} 份归档公告</em>
    </div>

    <div className="axis-wrap" role="img"
         aria-label={`证据方向轴：支持 ${counts.support ?? 0} 件、削弱 ${counts.counter ?? 0} 件、中性 ${counts.neutral ?? 0} 件`}>
      <div className="axis-rows">
        <span className="axis-row-label axis-row-label--up">支持</span>
        <span className="axis-row-label axis-row-label--mid">中性</span>
        <span className="axis-row-label axis-row-label--down">削弱</span>
      </div>
      <div className="axis-plot">
        <i className="axis-line" aria-hidden="true" />
        {/* 写下判断的那天。左边是你当初的依据，右边才是对它的检验 ——
            不标出来，两种意义完全不同的东西会被混在一起读。 */}
        {marker && <i className="axis-marker" style={{ left: `${layout.at(marker)}%` }}
                      title={`写下判断：${marker}`} />}
        {data.events.map((event) => {
          const tone = TONE[event.polarity] ?? TONE.neutral;
          return (
            <button type="button" key={event.id}
                    className={`axis-dot axis-dot--row${tone.row}${event.id === picked ? " axis-dot--on" : ""}`}
                    style={{ left: `${layout.at(event.date)}%`, background: tone.color }}
                    onClick={() => setPicked(event.id === picked ? null : event.id)}
                    title={`${event.date}　${tone.label}　${event.title.slice(0, 40)}`} />
          );
        })}
      </div>
      <div className="axis-scale">
        <span>{new Date(layout.from).toISOString().slice(0, 10)}</span>
        {marker && <span className="axis-scale-mark">写下判断 {marker}</span>}
        <span>{new Date(layout.to).toISOString().slice(0, 10)}</span>
      </div>
    </div>

    {opened && <div className="axis-card">
      <div className="axis-card-head">
        <span className="grade-chip" style={{
          background: `${(TONE[opened.polarity] ?? TONE.neutral).color}22`,
          color: (TONE[opened.polarity] ?? TONE.neutral).color,
        }}>{(TONE[opened.polarity] ?? TONE.neutral).label}</span>
        <time>{opened.date}</time>
        <button className="text-button" onClick={() => setPicked(null)}>收起</button>
      </div>
      <strong>{opened.title}</strong>
      {/* 理由必须显示。没有理由的方向不算数 —— 一个说不出为什么的「削弱」
          会让人白紧张一场，而下次真的削弱时他就不信了。 */}
      <p>{opened.reason}</p>
      <div className="axis-card-foot">
        {opened.source && <em>{opened.source}</em>}
        {opened.url && <a href={opened.url} target="_blank" rel="noreferrer">打开原始公告 ↗</a>}
      </div>
    </div>}

    <p className="chart-note">{data.boundary}</p>
  </>;
}
