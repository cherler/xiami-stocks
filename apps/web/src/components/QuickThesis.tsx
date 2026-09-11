/**
 * 三十秒写下一个判断。
 *
 * ## 它要对付的是什么
 *
 * 不是"字段太多"，是**路太长**：先建公司档案 → 等同步 → 走到那家公司的某个页签
 * → 填一堆东西。十分钟起步，而一闪而过的念头撑不到那里。
 *
 * 所以这个框：**从任何地方都能开，给个代码就能写**，没建档的会顺手建。
 *
 * ## 只问三件事
 *
 * 哪家 · 为什么 · 什么情况下我认错。其余全部走默认值——
 * **在这里多问一个字段，就多一次半途放弃的机会**，而那些东西事后都能补。
 *
 * ## 认错条件是唯一不肯降的那道摩擦
 *
 * 省掉它，剩下的是一句无法被推翻的感想：反证命中永远不会触发，复核无从谈起。
 * 那不是少填一栏，是这条记录作废。
 *
 * 但它是最难写的一栏——难在要凭空想出一个**具体到能被判定**的条件
 * （"基本面恶化"不算，什么叫恶化？）。所以候选由代码从这家公司自己的历史里算好，
 * 每条都带出处：点一下填进去，再改成自己的。
 */

import { useEffect, useState } from "react";

import { getQuickThesisContext, writeQuickThesis, type QuickThesisContext } from "../api";

function errorText(caught: unknown): string {
  return caught instanceof Error ? caught.message : String(caught);
}

function rich(text: string) {
  return text.split(/\*\*/).map((part, index) =>
    index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>);
}

export function QuickThesis({ symbol: fixedSymbol, onClose, onDone }: {
  symbol?: string;
  onClose: () => void;
  onDone?: (companyId: number) => void;
}) {
  const [symbol, setSymbol] = useState(fixedSymbol ?? "");
  const [context, setContext] = useState<QuickThesisContext | null>(null);
  const [claim, setClaim] = useState("");
  const [counter, setCounter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState<{ id: number; text: string } | null>(null);

  // 代码敲够六位就去把候选取回来。**不等你按回车**——
  // 多一次按键就多一分放弃的可能。
  useEffect(() => {
    const code = symbol.trim();
    if (code.length < 6) { setContext(null); return; }
    let live = true;
    getQuickThesisContext(code)
      .then((next) => { if (live) setContext(next); })
      .catch(() => { if (live) setContext(null); });
    return () => { live = false; };
  }, [symbol]);

  async function submit() {
    setBusy(true); setError("");
    try {
      const result = await writeQuickThesis({
        symbol: symbol.trim(), claim: claim.trim(), counter_condition: counter.trim(),
      });
      setDone({ id: result.company_id, text: result.note });
      setClaim(""); setCounter("");
    } catch (caught) { setError(errorText(caught)); } finally { setBusy(false); }
  }

  if (done) {
    return (
      <div className="qt">
        <div className="qt-head"><strong>写下了</strong>
          <button className="text-button" onClick={onClose}>关闭</button></div>
        <p className="qt-done">{done.text}</p>
        <div className="qt-actions">
          <button className="page-action" onClick={() => onDone?.(done.id)}>打开这家的档案</button>
          <button className="text-button" onClick={() => setDone(null)}>再写一条</button>
        </div>
      </div>
    );
  }

  return (
    <div className="qt">
      <div className="qt-head">
        <strong>写下一个判断</strong>
        <em>哪家 · 为什么 · 什么情况下我认错</em>
        <button className="text-button" onClick={onClose}>关闭</button>
      </div>

      <label className="qt-field">
        <span>哪家</span>
        <input value={symbol} disabled={Boolean(fixedSymbol)} maxLength={10}
               placeholder="六位代码，例如 600519"
               onChange={(e) => setSymbol(e.target.value)} />
      </label>
      {context && (
        <p className="qt-hint">
          {context.name ?? "未知"}
          {!context.known && <em>{context.note}</em>}
        </p>
      )}

      <label className="qt-field qt-field--wide">
        <span>为什么</span>
        <textarea value={claim} rows={2} maxLength={500}
                  placeholder="一句话说清你的判断"
                  onChange={(e) => setClaim(e.target.value)} />
      </label>

      <label className="qt-field qt-field--wide">
        <span>什么情况下我认错</span>
        <textarea value={counter} rows={2} maxLength={500}
                  placeholder="写成一句能判定真假的话"
                  onChange={(e) => setCounter(e.target.value)} />
      </label>

      {/* 最难写的一栏，候选由代码从这家公司自己的历史里算好，每条都带出处。
          **候选不是推荐**——它们的作用是让人看见"一个可判定的条件长什么样"。 */}
      {context && context.suggestions.length > 0 && (
        <div className="qt-suggest">
          <p>从它自己的历史里算出来的候选（点一下填进去，再改成你的）：</p>
          {context.suggestions.map((item, index) => (
            <button type="button" key={index} className="qt-chip"
                    disabled={!item.text}
                    onClick={() => item.text && setCounter(item.text)}>
              <strong>{item.text || "自己写一条"}</strong>
              <em>{rich(item.why)}</em>
            </button>
          ))}
        </div>
      )}

      {error && <p className="form-error">{rich(error)}</p>}

      <div className="qt-actions">
        <button className="page-action" disabled={busy || symbol.trim().length < 6}
                onClick={() => void submit()}>
          {busy ? "正在写下…" : "写下"}
        </button>
        <span className="qt-note">
          其余都走默认值，事后再补。<strong>只有认错条件不能空</strong>——
          没有它，这条记录就是一句无法被推翻的感想。
        </span>
      </div>
    </div>
  );
}
