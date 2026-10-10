/**
 * 这段涨跌属于什么类型。
 *
 * ## 它拆的是一种具体的焦虑
 *
 * > 很多基本面很差的股票连续涨停，我看不懂，也不敢参与。是不是我错过了什么？
 *
 * 看不懂一只票为什么涨，和这只票不值得买，是两件事。先把"它为什么涨"答出来，
 * 再决定要不要参与——**而不是反过来，先焦虑、再找理由。**
 *
 * ## 判据要摆出来，不只给结论
 *
 * 每条判据都是一句能拿库里的数字当场验算的话。只给"它属于题材情绪"这一个标签，
 * 使用者没办法复核，也**没办法不同意**——而不同意的权利是这个产品的前提。
 *
 * ## 「无法解释」和「没什么事发生」不是失败
 *
 * 一个什么都能解释的分类器等于没有分类器。查不出原因本身就是对决策有用的信息，
 * 它是「先别碰」最诚实的理由。这两种情况下那段模型解释**直接不跑**：
 * 能写出来的只能是编的，而编出来的解释比没有解释更糟。
 */

import { useCallback, useEffect, useState } from "react";

import { getCompanies, getRally, lookupRally, narrateRally, type RallyView } from "../api";
import type { CompanyRecord } from "../types";
import { useSpendGuard } from "../lib/credits";
import { PanelTitle } from "./PanelTitle";

function rich(text: string) {
  return text.split(/\*\*/).map((part, index) =>
    index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>);
}

const num = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined ? "—" : value.toFixed(digits);
const yi = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : `${(value / 1e8).toFixed(0)} 亿`;

export function RallyType({ onOpenCompany }: { onOpenCompany: (id: number) => void }) {
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [companyId, setCompanyId] = useState<number | null>(null);
  // **直接输代码那一路是刻意排在前面的。**
  // 使用者最想问的那几只（「那只很烂的股票凭什么连着涨停」）按定义就不在
  // 研究池里——他要是研究过它们，也就不会看不懂了。
  const [symbol, setSymbol] = useState("");
  const [window_, setWindow] = useState(20);
  const [view, setView] = useState<RallyView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [narrating, setNarrating] = useState(false);
  const guard = useSpendGuard();

  useEffect(() => {
    let live = true;
    getCompanies().then((rows) => {
      if (!live) return;
      setCompanies(rows);
      setCompanyId((current) => current ?? rows[0]?.id ?? null);
    }).catch((caught) => live && setError(caught instanceof Error ? caught.message : String(caught)));
    return () => { live = false; };
  }, []);

  const load = useCallback(async () => {
    const code = symbol.trim();
    if (!code && companyId === null) return;
    setBusy(true); setError("");
    try {
      setView(code ? await lookupRally(code, window_) : await getRally(companyId as number, window_));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught)); setView(null);
    } finally { setBusy(false); }
  }, [companyId, symbol, window_]);
  useEffect(() => { void load(); }, [load]);

  async function narrate() {
    // 池子外的票没有 company_id，那段解释暂时只对档案里的票开放。
    if (companyId === null || symbol.trim()) return;
    setNarrating(true);
    try { setView(await narrateRally(companyId, window_)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setNarrating(false); }
  }

  const facts = view?.facts;
  const verdict = view?.verdict;
  const narration = view?.narration;
  const fromUniverse = Boolean(facts?.source);
  const canNarrate = verdict?.ok && !fromUniverse
    && verdict.primary !== "unexplained" && verdict.primary !== "quiet";

  return <>
    <section className="page-intro archive-intro">
      <div>
        <span className="section-kicker">WHY</span>
        <h1>它为什么涨（或者跌）</h1>
        <p>{rich("看不懂一只票为什么涨，和这只票不值得买，是两件事。"
          + "**先把「它为什么涨」答出来，再决定要不要参与**——而不是先焦虑、再找理由。")}</p>
      </div>
      {facts?.ok && <div className="local-stamp"><span>{facts.name} · {facts.window_days} 日</span>
        <strong>{facts.change === null || facts.change === undefined ? "—"
          : `${facts.change > 0 ? "+" : ""}${facts.change.toFixed(1)}%`}</strong>
        <em>{facts.start_date} → {facts.end_date}</em></div>}
    </section>

    <section className="panel jd-panel">
      <div className="sw-controls">
        <label>
          <span>直接输代码（不必在研究池里）</span>
          <input type="text" inputMode="numeric" maxLength={6} placeholder="六位数字，如 600127"
                 value={symbol}
                 onChange={(event) => setSymbol(event.target.value.replace(/\D/g, ""))} />
        </label>
        <label>
          <span>或从研究池里挑</span>
          <select value={symbol.trim() ? "" : (companyId ?? "")}
                  onChange={(event) => { setSymbol(""); setCompanyId(Number(event.target.value)); }}>
            {symbol.trim() && <option value="">（正在看 {symbol}）</option>}
            {companies.map((company) =>
              <option key={company.id} value={company.id}>{company.name}（{company.symbol}）</option>)}
          </select>
        </label>
        <label>
          <span>窗口</span>
          <select value={window_} onChange={(event) => setWindow(Number(event.target.value))}>
            <option value={5}>近 5 个交易日</option>
            <option value={20}>近 20 个交易日</option>
            <option value={60}>近 60 个交易日</option>
          </select>
        </label>
        {companyId !== null && !symbol.trim() && <button type="button" className="text-button"
                onClick={() => onOpenCompany(companyId)}>打开公司档案 →</button>}
      </div>
      {error && <p className="form-error">{error}</p>}
      {busy && !view && <div className="empty-state">正在算…</div>}
      {facts && !facts.ok && <p className="empty-state">{facts.note}</p>}
    </section>

    {facts?.ok && verdict?.ok && <>
      <section className="panel jd-panel ry-verdict">
        <p className="ry-headline">{rich(verdict.headline ?? "")}</p>
        {/* **少了哪几样要写在结论旁边，不是藏在底数表里。**
            一份判据不全的结论跟判据齐全的结论长得一样，是最容易误导人的。 */}
        {fromUniverse && <div className="ry-partial">
          <p><strong>这只票不在你的研究池里</strong>，这份归因走的是全市场底座
             （{facts.start_date} → {facts.end_date}，{facts.window_days} 个交易日
             {facts.requested_window && facts.requested_window !== facts.window_days
               ? `；你选的是 ${facts.requested_window} 天，底座只攒到这么多`
               : ""}）。下面这几条<strong>取不到，所以按「不通过」算</strong>——
             查不到不等于没有：</p>
          <ul>{facts.unavailable?.map((line, index) => <li key={index}>{line}</li>)}</ul>
          <p className="ry-enrich">{facts.enrich_hint}</p>
        </div>}
        {verdict.suppressed_by_floor && <p className="ry-floor">
          {rich(`这 ${facts.window_days} 个交易日的幅度是 ${num(verdict.magnitude, 1)}%，`
            + `没到 ${verdict.floor}% 的归因门槛`
            // **门槛是怎么来的必须写出来。** 同样走 12%，在日波动 1% 的票上是件事，
            // 在日波动 4% 的票上是它每周都在做的事——不说依据，这个数就是个咒语。
            + (verdict.prior_daily_sigma
               ? `（按这只票自己的波动算：窗口之前的日波动 ${num(verdict.prior_daily_sigma * 100, 2)}%）`
               : "（缺窗口之前那段日线，用的是通用式子）")
            + "。**下面那些判据照常算，但不采信**——"
            + "不是每一段行情都有原因，给一段正常波动编一个故事，"
            + "会让你在下一次真有事发生时也照着故事读。")}
        </p>}
        <p className="ry-accounting">{rich(verdict.accounting_note ?? "")}</p>
      </section>

      <section className="panel jd-panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">判据</span>
          <PanelTitle hint="每条都能拿库里的数字当场验算。只给结论的话，你没办法复核，也没办法不同意。">
            每一条是怎么判的
          </PanelTitle>
        </div></div>
        <div className="ry-types">
          {(verdict.types ?? []).map((type) => <article key={type.key}
                  className={`ry-type${type.hit ? " ry-type--hit" : ""}`}>
            <header>
              <h4>{type.label}</h4>
              {type.total > 0 && <span className="ry-score">{type.hit_count}/{type.total}</span>}
            </header>
            <p className="ry-means">{type.means}</p>
            <ul className="ry-checks">
              {type.checks.map((check, index) => <li key={index} className={check.ok ? "ry-ok" : ""}>
                <i aria-hidden="true">{check.ok ? "✓" : "○"}</i>
                <span>{check.text}</span>
                <em>{rich(check.detail)}</em>
              </li>)}
            </ul>
            {type.hit && <p className="ry-foryou">{rich(type.for_you)}</p>}
          </article>)}
        </div>
      </section>

      <section className="panel jd-panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">底数</span>
          <PanelTitle hint="判据用到的原始数字，连同它取不到时的说法。">判据背后的数</PanelTitle>
        </div></div>
        <dl className="ry-facts">
          <div><dt>区间涨跌</dt><dd>{num(facts.change, 2)}%（{num(facts.start_close)} → {num(facts.end_close)}）</dd></div>
          <div><dt>同行业中位</dt><dd>
            {facts.industry?.median_change === null || facts.industry?.median_change === undefined
              ? (facts.industry?.note || "—")
              : `${facts.industry.name} ${facts.industry.median_change.toFixed(2)}%（${facts.industry.peer_count} 家）`}
          </dd></div>
          <div><dt>行业内分位</dt><dd>{facts.industry?.rank_percentile === null
            || facts.industry?.rank_percentile === undefined ? "—" : `${facts.industry.rank_percentile}%`}</dd></div>
          <div><dt>量能</dt><dd>{facts.volume?.ratio === null || facts.volume?.ratio === undefined
            ? "缺成交量" : `比前一段放大 ${facts.volume.ratio.toFixed(2)} 倍`}</dd></div>
          <div><dt>涨跌停（{facts.board} {facts.limit_percent}%）</dt>
            <dd>{facts.limit_up_days} 天，最长连续 {facts.max_limit_streak} 天</dd></div>
          <div><dt>换手率</dt><dd>{num(facts.turnover_rate, 2)}%</dd></div>
          <div><dt>流通市值</dt><dd>{yi(facts.float_market_cap)}</dd></div>
          <div><dt>PE(TTM)</dt><dd>
            {num(facts.valuation?.pe_start, 1)}（{facts.valuation?.pe_start_date ?? "日期不明"}）
            {" → "}{num(facts.valuation?.pe_end, 1)}
            {facts.valuation?.pe_end_derived ? "（推算）" : ""}
          </dd></div>
          <div><dt>起点 PE 分位</dt><dd>{facts.valuation?.pe_percentile_start === null
            || facts.valuation?.pe_percentile_start === undefined
            ? `样本 ${facts.valuation?.pe_sample ?? 0} 个，算不出分位`
            : `${facts.valuation.pe_percentile_start.toFixed(0)}%（样本 ${facts.valuation.pe_sample} 个）`}</dd></div>
          <div><dt>窗口内新报告期</dt><dd>{facts.valuation?.report_in_window
            ? facts.valuation.report_dates.join("、") : "没有"}</dd></div>
          <div><dt>公告后三天</dt><dd>{facts.post_event
            ? `覆盖 ${facts.post_event.covered_days}/${facts.post_event.tradable_days} 天，`
              + `贡献 ${(facts.post_event.share * 100).toFixed(0)}% 的幅度，`
              + `提升 ${facts.post_event.lift?.toFixed(2) ?? "—"} 倍`
            : "没有可对齐的公告日"}</dd></div>
        </dl>
        <p className="ry-caveat">{facts.valuation?.report_date_caveat}</p>
      </section>

      {/* **同环节的同行逐家点名。**
          申万「电力设备」有 377 家，混着光伏、风电、电网设备——拿它的中位数
          去问「只有它在跌吗」，答案被稀释掉了。环节小得多（中位 2 家），
          所以这里不摆中位数，摆名字和各自的涨跌。 */}
      <section className="panel jd-panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">同环节</span>
          <PanelTitle hint="环节归属与出处来自 earth-atlas 产业链底图，每家都有一手引句。">
            只有它在动，还是同环节都在动
          </PanelTitle>
        </div></div>
        {(facts.chain_peers?.groups?.length ?? 0) === 0
          ? <p className="empty-state">{facts.chain_peers?.note || "没有同环节数据。"}</p>
          : <>
            <div className="ry-chains">
              {facts.chain_peers?.groups.map((group) => {
                return <article key={group.key}
                        className={`ry-chain${group.key === facts.chain_peers?.best ? " ry-chain--used" : ""}`}>
                  <header>
                    <h4>{group.chain_label}<i>·</i>{group.segment_label}</h4>
                    <span className="ry-chain-n">
                      {group.peer_count} 家{group.enough ? "" : "（不足 3 家，只点名）"}
                    </span>
                  </header>
                  {group.what && <p className="ry-chain-what">{group.what}</p>}
                  <ul className="ry-chain-list">
                    {group.members.map((m) => <li key={m.symbol}
                            className={m.self ? "ry-chain-self" : ""}>
                      <span>{m.name}</span>
                      <em>{m.change === null ? "无行情"
                        : `${m.change > 0 ? "+" : ""}${m.change.toFixed(1)}%`}</em>
                      {!m.self && m.source_url && <a href={m.source_url} target="_blank"
                              rel="noreferrer" title={m.source_title}>出处</a>}
                    </li>)}
                  </ul>
                </article>;
              })}
            </div>
            {facts.chain_peers?.note && <p className="ry-chain-note">{facts.chain_peers.note}</p>}
            {verdict.peer_source && <p className="ry-chain-note">
              {rich(`「行业性」那条判据用的是 **${verdict.peer_source}**。`
                + (facts.chain_peers?.best ? "" : "同环节不足 3 家，退回了申万一级——"
                   + "那是个很粗的集合，读它的中位数时要记住这一点。"))}
            </p>}
          </>}
      </section>

      {(facts.events?.length ?? 0) > 0 && <section className="panel jd-panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">{facts.event_count} 条 · 其中 {facts.high_relevance_count} 条实质</span>
          <PanelTitle hint="没分过级的公告在这里按规则现算了一次——「没分级」不等于「不重要」。">
            窗口里发生了什么
          </PanelTitle>
        </div></div>
        <ul className="ry-events">
          {facts.events?.map((event, index) => <li key={index}
                  className={event.relevance === "高" ? "ry-event--high" : ""}>
            <span className="ry-event-date">{event.event_date}</span>
            <span className="ry-event-rel">{event.relevance}</span>
            <span className="ry-event-title">{event.title}</span>
            <em>{event.relevance_from}{event.relevance_reason ? ` · ${event.relevance_reason}` : ""}</em>
          </li>)}
        </ul>
      </section>}

      <section className="panel jd-panel ry-narrate">
        <div className="panel-heading"><div>
          <span className="eyebrow">可选 · 要花积分</span>
          <PanelTitle hint="分类由规则层定死，模型改不了；它说出来的数字在事实表里找不到出处会被标出来。">
            让模型把这些讲成一段人话
          </PanelTitle>
        </div></div>
        {/* **不跑模型有两种原因，说法不能混。**
            一种是"能写出来的只能是编的"（判成无法解释 / 没什么事发生），
            一种是"这只票的底数本来就不全"（池子外）。
            混成一句的话，查池外票的人会以为是他那只票查不出原因。 */}
        {!canNarrate ? <p className="empty-state">
          {rich(fromUniverse
            ? "这只票不在你的研究池里，成交量、公告、历史估值分位三样都取不到——"
              + "**底数不全的时候让模型写解释，写出来的只能是编的**。"
              + "想让它讲，先把这只票建成公司档案并同步一次行情历史。"
            : "规则层判成「" + (verdict.types?.find((t) => t.key === verdict.primary)?.label ?? "—")
              + "」，这一步不跑模型：**能写出来的只能是编的**，而编出来的解释比没有解释更糟——"
              + "你会照着它做决定。")}
        </p> : <>
          <button type="button" className="page-action" disabled={narrating}
                  onClick={async () => {
                    // **必须 await。** 忘了的话 `if (!Promise)` 恒为假，
                    // 会绕过确认框直接开跑并扣钱（lib/confirm.test.ts 扫这一点）。
                    if (await guard("rally-narrate", "让模型把规则层算出来的这些数字讲成一段人话。")) void narrate();
                  }}>
            {narrating ? "模型正在写…" : "写一段解释"}
          </button>
          {narration?.note && <p className="ry-note">{narration.note}</p>}
          {narration?.ok && <div className="ry-story">
            <p>{narration.story}</p>
            <p className="ry-meaning"><strong>对做基本面的人意味着什么：</strong>{narration.meaning}</p>
            {(narration.what_to_check?.length ?? 0) > 0 && <>
              <h4>接下来该自己核的</h4>
              <ol>{narration.what_to_check?.map((item, index) => <li key={index}>{item}</li>)}</ol>
            </>}
            {(narration.untraceable?.length ?? 0) > 0 && <p className="ry-untraceable">
              <strong>这几个数在事实表里找不到出处：{narration.untraceable?.join("、")}。</strong>
              可能是它自己算的差值，也可能是编的。用之前请自己核一眼。
            </p>}
            <p className="ry-model">{narration.model}
              {narration.credits ? ` · 花了 ${narration.credits} 积分` : ""}</p>
          </div>}
        </>}
      </section>
    </>}
  </>;
}
