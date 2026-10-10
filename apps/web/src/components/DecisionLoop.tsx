/** 跟踪首页只聚合已有资料；规则与状态变更仍由用户在详情中确认。 */

import { useCallback, useEffect, useState } from "react";

import {
  enrollDecisionCard, evaluateDecisionTriggers, getDecisionLoop,
  getDecisionCard, moveDecisionState, saveDecisionCard,
  type DecisionLoopView, type DecisionCardView,
  recordFill, deleteFill,
} from "../api";
import { trackingRows, researchSummary } from "../lib/tracking";
import "./DecisionLoop.css";
import { PanelTitle } from "./PanelTitle";

function rich(text: string) {
  return text.split(/\*\*/).map((part, index) =>
    index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>);
}

const THESIS_LABELS: Record<string, string> = { intact: "成立", watching: "待观察", challenged: "受挑战", broken: "已破坏" };

const MONEY = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });

/** 价格带梯子。四段从高到低，当前价用一条横线标出来落在哪一段。 */
function BandLadder({ card }: { card: DecisionCardView }) {
  const keys = card.band_specs.map((spec) => spec.key);
  const filled = keys.filter((key) => typeof card.bands[key] === "number");
  if (filled.length !== keys.length) {
    return <p className="dl-band-empty">
      还没定价格带。<strong>不是「买点 = 280」这一个数字</strong>——
      一个数字把决策二元化成「能买 / 不能买」，而真实的判断是分层的：
      310 尚可、290 不错、280 很好、270 非常舒服，对应的是不同的仓位，不是不同的是非。
    </p>;
  }
  return <ol className="dl-ladder">
    {card.band_specs.map((spec, index) => {
      // **存的是每一段的上沿**：跌到这个价才算进这一段。
      // 所以这一段的区间是「上沿」到「下一段的上沿」，最低那一段是「及以下」。
      // 第一版按下沿渲染，于是梯子写着「观察区 310 以上」而判定把 305 判进观察区
      // —— 页面自己跟自己说的不一样。
      const top = card.bands[spec.key];
      const next = index === keys.length - 1 ? null : card.bands[keys[index + 1]];
      const active = card.current_band === spec.key;
      return <li key={spec.key} className={`dl-rung${active ? " dl-rung--here" : ""}`}>
        <span className="dl-rung-range">
          {next === null || next === undefined
            ? `${MONEY(top)} 及以下`
            : `${MONEY(next)} – ${MONEY(top)}`}
        </span>
        <span className="dl-rung-label">{spec.label}</span>
        <span className="dl-rung-means">{spec.means.split(/\*\*/).map((part, i) =>
          i % 2 === 1 ? <strong key={i}>{part}</strong> : <span key={i}>{part}</span>)}</span>
        {active && <span className="dl-rung-now">现价 {MONEY(card.price)} 在这里</span>}
      </li>;
    })}
    {card.current_band === null && card.price !== null && <li className="dl-rung dl-rung--above">
      <span className="dl-rung-range">{MONEY(card.price)}</span>
      <span className="dl-rung-label">还没进任何一段</span>
      <span className="dl-rung-means">高于观察区上沿。<strong>这不叫错过，这叫在等。</strong></span>
    </li>}
  </ol>;
}

function CardEditor({ card, onSaved }: { card: DecisionCardView; onSaved: () => void }) {
  const [watch, setWatch] = useState(card.watch_reason);
  const [bands, setBands] = useState<Record<string, string>>(() =>
    Object.fromEntries(card.band_specs.map((spec) =>
      [spec.key, card.bands[spec.key] === undefined ? "" : String(card.bands[spec.key])])));
  const [plan, setPlan] = useState<Record<string, string>>(() =>
    Object.fromEntries(card.plan_fields.map((field) =>
      [field.key, card.position_plan[field.key] === undefined ? "" : String(card.position_plan[field.key])])));
  const [order, setOrder] = useState<Record<string, string>>(() =>
    Object.fromEntries(card.order_fields.map((field) =>
      [field.key, card.order_plan[field.key] === undefined ? "" : String(card.order_plan[field.key])])));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true); setError("");
    try {
      const numericBands: Record<string, number | null> = {};
      for (const [key, value] of Object.entries(bands)) {
        numericBands[key] = value.trim() === "" ? null : Number(value);
      }
      const payloadPlan: Record<string, number | string | null> = {};
      for (const field of card.plan_fields) {
        const value = plan[field.key];
        if (value === undefined || value.trim() === "") { payloadPlan[field.key] = null; continue; }
        payloadPlan[field.key] = field.kind === "number" ? Number(value) : value;
      }
      const payloadOrder: Record<string, number | string | null> = {};
      for (const field of card.order_fields) {
        const value = order[field.key];
        if (value === undefined || value.trim() === "") { payloadOrder[field.key] = null; continue; }
        payloadOrder[field.key] = field.kind === "number" ? Number(value) : value;
      }
      await saveDecisionCard(card.company_id,
        { watch_reason: watch, bands: numericBands, position_plan: payloadPlan,
          order_plan: payloadOrder });
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally { setBusy(false); }
  }

  return <div className="dl-editor">
    <label className="dl-field dl-field--wide" data-anchor="watch">
      <span>为什么关注它</span>
      <textarea rows={2} value={watch} onChange={(event) => setWatch(event.target.value)}
                placeholder="一句话。闭环第一格只要这一句。" />
    </label>

    <fieldset className="dl-fieldset" data-anchor="plan">
      <legend>价格带（四段的上沿，从高到低）</legend>
      <p className="dl-hint">{rich("填的是**上沿**：跌到这个价才算进这一段——写 300，"
        + "那么 300 算合理区、301 还不算。"
        + "要么一段都不填，要么四段填全：**半张价格带在页面上跟整张长得一样**，"
        + "却会在触发时漏掉一整段。")}</p>

      {/* 估值 → 价格带的那根线。
          原来这四个数要从零手填，而隔壁「我的估值」早就算出了基准每股价值——
          两个模块之间没有任何连接。实测后果：23 笔买入，纪律判定覆盖 0 笔。 */}
      {card.suggested_bands && <div className="dl-suggest">
        <div className="dl-suggest-head">
          <strong>按我的估值算，这四段大概是：</strong>
          <button type="button" className="text-button" onClick={() => setBands(
            Object.fromEntries(card.suggested_bands!.rows.map((row) => [row.key, String(row.value)])))}>
            填进去 ↓
          </button>
        </div>
        <ul className="dl-suggest-rows">
          {card.suggested_bands.rows.map((row) => <li key={row.key}>
            <b>{card.band_specs.find((spec) => spec.key === row.key)?.label ?? row.key}</b>
            <strong>{row.value.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}</strong>
            <em>{row.formula}</em>
          </li>)}
        </ul>
        <p className="dl-suggest-note">{rich(card.suggested_bands.note)}</p>
        {/* **出处和日期跟数字一起给。** 一个不知道哪来、什么时候算的建议值，
            跟一个编出来的默认值没有区别。 */}
        <p className="dl-suggest-src">
          依据：{card.suggested_bands.base_report_date ?? "不确定是哪一期"} 的财报，
          基准每股价值 {card.suggested_bands.per_share_base}
          {card.suggested_bands.as_of ? `，估值存于 ${card.suggested_bands.as_of.slice(0, 10)}` : ""}。
        </p>
      </div>}

      <div className="dl-grid">
        {card.band_specs.map((spec) => <label key={spec.key} className="dl-field">
          <span>{spec.label}</span>
          <input type="number" step="0.01" value={bands[spec.key] ?? ""}
                 onChange={(event) => setBands({ ...bands, [spec.key]: event.target.value })} />
          <em>{rich(spec.means)}</em>
        </label>)}
      </div>
    </fieldset>

    <fieldset className="dl-fieldset">
      <legend>仓位计划</legend>
      <p className="dl-hint">{rich("**价格解决赔率，仓位解决判断错误。** "
        + "你不需要预测最低点，你需要定义不同价格下愿意承担多少仓位。")}</p>
      <div className="dl-grid">
        {card.plan_fields.map((field) => <label key={field.key}
              className={`dl-field${field.kind === "text" ? " dl-field--wide" : ""}`}>
          <span>{field.label}{field.required && <i className="dl-req">必填</i>}</span>
          {field.kind === "number"
            ? <input type="number" step="0.5" value={plan[field.key] ?? ""}
                     onChange={(event) => setPlan({ ...plan, [field.key]: event.target.value })} />
            : <input type="text" value={plan[field.key] ?? ""}
                     onChange={(event) => setPlan({ ...plan, [field.key]: event.target.value })} />}
          <em>{field.hint.split(/\*\*/).map((part, i) =>
            i % 2 === 1 ? <strong key={i}>{part}</strong> : <span key={i}>{part}</span>)}</em>
        </label>)}
      </div>
    </fieldset>

    <fieldset className="dl-fieldset">
      <legend>这一笔的下单计划</legend>
      <p className="dl-hint">{rich("跟上面的仓位计划不是一回事：那个是整只票的总规划，"
        + "**这个是「我现在决定下的这一单」**。成交之后要拿它对账——"
        + "成交价离你写下的计划价多远，是「计划外交易」这个指标唯一的依据。")}</p>
      <div className="dl-grid">
        {card.order_fields.map((field) => <label key={field.key}
              className={`dl-field${field.kind === "text" ? " dl-field--wide" : ""}`}>
          <span>{field.label}{field.required && <i className="dl-req">必填</i>}</span>
          {field.kind === "number"
            ? <input type="number" step="0.01" value={order[field.key] ?? ""}
                     onChange={(event) => setOrder({ ...order, [field.key]: event.target.value })} />
            : <input type="text" value={order[field.key] ?? ""}
                     onChange={(event) => setOrder({ ...order, [field.key]: event.target.value })} />}
          <em>{rich(field.hint)}</em>
        </label>)}
      </div>
    </fieldset>

    {error && <p className="form-error">{error}</p>}
    <button type="button" className="page-action" onClick={() => void save()} disabled={busy}>
      {busy ? "正在存…" : "存下来"}
    </button>
  </div>;
}

/** 每一块各自定下来的时间。
 *
 * 为什么不是整张卡一个 updated_at：那个会被"今天改了仓位计划"刷掉，
 * 于是「这组价格带有多旧」这个唯一的信号消失。而价格带没有自己的有效期，
 * 它的有效期是它依据的那期财报的有效期。
 *
 * **没有时间戳就明说不知道**，不要显示成今天——老卡片是在这个字段存在之前
 * 定的，把它们画成"刚定的"是把不知道说成了知道。 */
function BlockStamps({ card }: { card: DecisionCardView }) {
  const blocks: { key: string; label: string; filled: boolean }[] = [
    { key: "bands", label: "价格带", filled: Object.keys(card.bands).length > 0 },
    { key: "position_plan", label: "仓位计划", filled: Object.keys(card.position_plan).length > 0 },
    { key: "order_plan", label: "下单计划", filled: Object.keys(card.order_plan).length > 0 },
  ].filter((block) => block.filled);
  if (blocks.length === 0) return null;
  return <ul className="dl-stamps">
    {blocks.map((block) => {
      const stamp = card.block_stamps[block.key];
      const when = stamp?.set_at ? stamp.set_at.slice(0, 10) : null;
      const basis = block.key === "bands" ? stamp?.base_report_date : null;
      return <li key={block.key}>
        <b>{block.label}</b>
        <span>{when ? `${when} 定的` : "不知道什么时候定的"}</span>
        {basis && <em>依据 {basis} 财报</em>}
      </li>;
    })}
  </ul>;
}

/** 登记一次真实成交。
 *
 * **这是「计划内 / 计划外」现在唯一的入口。** 原来那个指标查账本里的 buy 流水，
 * 而持仓 2026-09-23 改成「只记股数和成本价」之后，账本里再也不会有 buy ——
 * 指标会永久归零而且不报错（页面上像"你还没交易过"）。
 *
 * 放在卡上而不是账本里，是因为它**不是记账，是决策的结果**：
 * 你按下单的那一刻填一次，一个动作，不用事后回来补。
 *
 * 登记**不改持仓**：持仓由你自己填。混在一起的话，登记 100 股会让持仓
 * 凭空多 100 股，而你并没有那么填。 */
function FillBar({ card, onDone }: { card: DecisionCardView; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [price, setPrice] = useState("");
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10));
  const [shares, setShares] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const planned = typeof card.order_plan.price === "number" ? card.order_plan.price : null;
  const typed = Number(price);
  // 边填边显示偏离——**成交之后再算就晚了**，那时你已经买完了。
  const drift = planned && planned > 0 && Number.isFinite(typed) && typed > 0
    ? (typed / planned - 1) * 100 : null;

  async function submit() {
    const value = Number(price);
    if (!Number.isFinite(value) || value <= 0) { setError("成交价要填一个大于 0 的数。"); return; }
    setBusy(true); setError("");
    try {
      await recordFill(card.company_id, {
        price: value, filled_on: day,
        shares: shares.trim() === "" ? null : Number(shares),
      });
      setPrice(""); setShares(""); setOpen(false);
      onDone();
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }

  async function remove(fillId: number) {
    setBusy(true); setError("");
    try { await deleteFill(fillId); onDone(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }

  return <div className="dl-fills">
    {card.fills.length > 0 && <ul className="dl-fill-list">
      {card.fills.map((fill) => {
        const gap = fill.planned_price && fill.planned_price > 0
          ? (fill.price / fill.planned_price - 1) * 100 : null;
        return <li key={fill.id}>
          <span className="dl-fill-when">{fill.filled_on}</span>
          <strong>{MONEY(fill.price)}</strong>
          {fill.shares !== null && <em>{fill.shares.toLocaleString("zh-CN")} 股</em>}
          {fill.planned_price !== null && <span className="dl-fill-gap">
            计划 {MONEY(fill.planned_price)}
            {gap !== null && `　偏离 ${gap > 0 ? "+" : ""}${gap.toFixed(1)}%`}
          </span>}
          <button type="button" className="text-button" disabled={busy}
            onClick={() => void remove(fill.id)}>删</button>
        </li>;
      })}
    </ul>}

    {open ? <div className="dl-fill-form">
      <label>成交价<input type="number" step="0.01" value={price} autoFocus
        onChange={(event) => setPrice(event.target.value)} /></label>
      <label>日期<input type="date" value={day} max={new Date().toISOString().slice(0, 10)}
        onChange={(event) => setDay(event.target.value)} /></label>
      <label>股数（可不填）<input type="number" step="1" value={shares}
        onChange={(event) => setShares(event.target.value)} /></label>
      <button type="button" className="page-action" disabled={busy}
        onClick={() => void submit()}>{busy ? "…" : "登记"}</button>
      <button type="button" className="text-button" onClick={() => setOpen(false)}>取消</button>
      {drift !== null && <p className="dl-fill-drift">
        计划价 {MONEY(planned)}，这一笔{drift > 0 ? "贵" : "便宜"} {Math.abs(drift).toFixed(1)}%。
      </p>}
    </div>
    : <button type="button" className="text-button" onClick={() => setOpen(true)}>
        ＋ 登记一笔成交
      </button>}
    {error && <p className="form-error">{error}</p>}
    <p className="dl-fill-note">{rich(
      "在你真下单的那一刻记一次。**登记不改持仓**——持仓由你自己在持仓账本里填。"
      + "这一笔是「计划内 / 计划外」唯一的依据：它拿你写下的计划价和四段价格带对账。")}</p>
  </div>;
}

function MoveBar({ card, onMoved }: { card: DecisionCardView; onMoved: () => void }) {
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const chosen = card.targets.find((item) => item.state === target);

  async function move() {
    setBusy(true); setError("");
    try { await moveDecisionState(card.company_id, target, reason); setReason(""); setTarget(""); onMoved(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }

  // **理由不再一律必填。** 往前走的那一步，理由就是"条件齐了"——那句话系统
  // 自己知道，让人再打一遍是纯粹的税，而税收够了人就不推进了。
  // 退回 / 搁置 / 决定买 仍然要自己写，`reason_why` 会说明为什么。
  const mustType = chosen?.reason_required ?? false;
  const canMove = Boolean(target) && (!mustType || reason.trim().length > 0);

  return <div className="dl-move">
    <div className="dl-move-row">
      <select value={target} onChange={(event) => setTarget(event.target.value)}>
        <option value="">推进到…</option>
        {card.targets.map((item) =>
          <option key={item.state} value={item.state}>{item.label}{item.ok ? "" : "（条件未满足）"}</option>)}
      </select>
      <input type="text" value={reason}
             placeholder={!chosen ? "先选要推进到哪一格"
               : mustType ? "这一步必须自己写一句"
               : chosen.auto_reason || "留空就由系统替你写"}
             onChange={(event) => setReason(event.target.value)} />
      <button type="button" className="page-action" disabled={busy || !canMove}
              onClick={() => void move()}>{busy ? "…" : "推进"}</button>
    </div>
    {/* 留空会写进库的那一句，**先给人看见**——不然"系统替你写"就是个黑箱。 */}
    {chosen && !mustType && !reason.trim() && chosen.auto_reason && <p className="dl-move-auto">
      留空的话会记成：<em>{chosen.auto_reason}</em>　想写别的就直接改。
    </p>}
    {chosen && mustType && <p className="dl-move-must">{rich(chosen.reason_why)}</p>}
    {chosen && !chosen.ok && <div className="dl-blocked">
      <p>{rich(chosen.reason)}</p>
      {chosen.missing.length > 0 && <ul>{chosen.missing.map((miss) =>
        <li key={miss.key}><strong>{miss.label}</strong>：{miss.fix}</li>)}</ul>}
    </div>}
    {error && <p className="form-error">{error}</p>}
  </div>;
}

function Card({ companyId, onBack, onOpenCompany, onOpenPortfolio }: {
  companyId: number; onBack: () => void;
  onOpenCompany: (id: number, tab?: string) => void;
  onOpenPortfolio: () => void;
}) {
  const [card, setCard] = useState<DecisionCardView | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { setCard(await getDecisionCard(companyId)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
  }, [companyId]);
  useEffect(() => { void load(); }, [load]);

  if (error) return <p className="form-error">{error}</p>;
  if (!card) return <div className="empty-state">正在读取…</div>;

  return <>
    <section className="page-intro archive-intro">
      <div>
        <button type="button" className="text-button" onClick={onBack}>返回跟踪清单</button>
        <h1>{card.name}<em className="dl-symbol">{card.symbol}</em></h1>
        <p className="dl-state-line">
          <span className={`dl-chip dl-chip--${card.state}`}>{card.state_label}</span>
          {rich(card.state_means)}
        </p>
        <p className="dl-next">下一步：{card.state_next}</p>
      </div>
      <div className="local-stamp"><span>现价</span>
        <strong>{MONEY(card.price)}</strong>
        <em>{card.price_date ?? "无行情"}{card.current_band_label ? ` · ${card.current_band_label}` : ""}</em>
      </div>
    </section>

    {card.state === "committed" && <section className="panel jd-panel dl-committed">
      <div className="panel-heading"><div>
        <span className="eyebrow">这一笔</span>
        <PanelTitle hint="成交之后账本会自动把它推成「持仓中」，并拿计划价对账。">
          决定买了，还没成交
        </PanelTitle>
      </div></div>
      <dl className="dl-order">
        <div><dt>计划成交价</dt><dd>{MONEY(card.order_plan.price as number)}</dd></div>
        <div><dt>这一笔</dt><dd>{String(card.order_plan.fraction ?? "—")}</dd></div>
        <div><dt>现价</dt><dd>{MONEY(card.price)}{card.current_band_label ? `　${card.current_band_label}` : ""}</dd></div>
      </dl>
      {card.order_plan.why_now && <p className="dl-order-why">{String(card.order_plan.why_now)}</p>}
    </section>}

    {card.last_trigger && <section className="panel jd-panel dl-trigger">
      <div className="panel-heading"><div>
        <span className="eyebrow">最近一次触发</span>
        <PanelTitle hint="价格到了只说明该重新看一眼，中间隔着一次「为什么会跌到这里、原假设还成立吗」。">
          价格触发 ≠ 下单
        </PanelTitle>
      </div></div>
      <p className="dl-trigger-line">
        {card.last_trigger.date} · {MONEY(card.last_trigger.price)} 进入
        <strong>{card.last_trigger.label}</strong>
      </p>
      <ol className="dl-checklist">
        {card.checklist.map((item, index) => <li key={index}>{item}</li>)}
      </ol>
    </section>}

    <section className="panel jd-panel">
      <div className="panel-heading"><div>
        <span className="eyebrow">状态</span>
        <PanelTitle hint="每一条守卫都是一句机器能判的话——判不了的不许写进来。">
          现在能走到哪一格
        </PanelTitle>
      </div></div>
      <ul className="dl-guards">
        {card.guards.map((guard) => <li key={guard.key} className={guard.ok ? "dl-guard--ok" : ""}>
          <i aria-hidden="true">{guard.ok ? "✓" : "○"}</i>
          <span>{guard.label}</span>
          {!guard.ok && <em>{rich(guard.fix)}</em>}
          {/* **一句"去公司档案的逻辑与证据"不算入口。** 差一件事就给一个
              能直接点的落点：卡上的滚过去并聚焦，别处的带页签跳过去。 */}
          {!guard.ok && guard.goto && <button type="button" className="text-button dl-guard-go"
            onClick={() => {
              const target = guard.goto!;
              if (target.where === "company") { onOpenCompany(card.company_id, target.tab); return; }
              if (target.where === "portfolio") { onOpenPortfolio(); return; }
              const node = document.querySelector<HTMLElement>(`[data-anchor="${target.anchor}"]`);
              node?.scrollIntoView({ behavior: "smooth", block: "center" });
              node?.querySelector<HTMLElement>("textarea, input")?.focus();
            }}>{guard.goto.label} →</button>}
        </li>)}
      </ul>
      <MoveBar card={card} onMoved={() => void load()} />
      {card.blocked.length > 0 && <div className="dl-forbidden">
        <h4>这几条路是关着的，不是坏了</h4>
        {card.blocked.map((item) => <p key={item.state}>
          <strong>→ {item.label}</strong>{rich(item.reason)}
        </p>)}
      </div>}
    </section>

    <section className="panel jd-panel">
      <div className="panel-heading"><div>
        <span className="eyebrow">价格与仓位</span>
        <PanelTitle hint="价格带记的是每一段的上沿，从高到低；四段必须一起填。跌到这个价就算进了这一段。">
          什么价、多大仓位
        </PanelTitle>
      </div>
      <button type="button" className="text-button"
              onClick={() => onOpenCompany(card.company_id)}>打开公司档案 →</button>
      </div>
      {/* **「在过去正确的记录数字，放在现在就是错的」** —— 所以每一块都要
          说清自己是什么时候定的、依据哪一期财报。用的不是整张卡的 updated_at：
          今天改一下仓位计划，那个就被刷成今天，而价格带其实还是去年那组。 */}
      <BlockStamps card={card} />
      {card.bands_stale && <p className="dl-stale">{rich(card.bands_stale)}</p>}
      <BandLadder card={card} />
      {/* 成交登记紧挨着价格带：判定「计划内」用的就是这两样
          ——成交价落在哪一段、当时卡片停在哪一格。 */}
      <FillBar card={card} onDone={() => void load()} />
      {card.reconcile.length > 0 && <div className="dl-reconcile">
        <h4>这几个数对一下</h4>
        {card.reconcile.map((line, index) => <p key={index}>{rich(line)}</p>)}
      </div>}
      <CardEditor card={card} onSaved={() => void load()} />
    </section>

    <section className="panel jd-panel">
      <div className="panel-heading"><div>
        <span className="eyebrow">推进史</span>
        <PanelTitle hint="退回也记。把「我从等待买入退回研究中」抹掉，等于把自己承认想错了的那一刻抹掉。">
          我什么时候、为什么动的
        </PanelTitle>
      </div></div>
      {card.history.length === 0 ? <p className="empty-state">还没有推进记录。</p>
        : <ol className="dl-history">
          {card.history.map((move, index) => <li key={index}>
            <span className="dl-history-when">{move.created_at.slice(0, 16).replace("T", " ")}</span>
            <span className="dl-history-move">
              {card.states[move.from_state] ?? move.from_state} → <strong>{card.states[move.to_state] ?? move.to_state}</strong>
            </span>
            <span className="dl-history-actor">{move.actor}</span>
            {move.price_at_move !== null && <span className="dl-history-price">价 {MONEY(move.price_at_move)}</span>}
            <p>{move.reason}</p>
          </li>)}
        </ol>}
    </section>
  </>;
}

export function DecisionLoop({ onOpenCompany, onOpenPortfolio }: {
  onOpenCompany: (id: number, tab?: string) => void;
  onOpenPortfolio: () => void;
}) {
  const [board, setBoard] = useState<DecisionLoopView | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [scanNote, setScanNote] = useState("");
  const [readAt, setReadAt] = useState("");
  const [query, setQuery] = useState("");
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [limit, setLimit] = useState(12);

  const load = useCallback(async () => {
    try {
      setBoard(await getDecisionLoop()); setError("");
      setReadAt(new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }));
      return true;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return false;
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function refresh(checkPrices = false) {
    setBusy(true); setScanNote(""); setError("");
    try {
      if (checkPrices) {
        const result = await evaluateDecisionTriggers();
        if (await load()) setScanNote(result.count === 0
          ? "本次检查未新增触发记录，使用的是已保存的行情。"
          : `有 ${result.count} 家进入设定区间，已排在前面。`);
      } else await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally { setBusy(false); }
  }

  async function startTracking(companyId: number) {
    setBusy(true); setError("");
    try { await enrollDecisionCard(companyId); setOpen(companyId); }
    catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }

  if (open !== null) {
    return <Card companyId={open} onBack={() => { setOpen(null); void load(); }}
                 onOpenCompany={onOpenCompany} onOpenPortfolio={onOpenPortfolio} />;
  }
  if (!board) return <div className="dl-tracking-message" role={error ? "alert" : "status"}>
    <p>{error || "正在读取你的研究…"}</p>
    {error && <button type="button" className="text-button" disabled={busy}
      onClick={() => void refresh()}>重新读取</button>}
  </div>;

  const rows = trackingRows(board);
  const attention = rows.filter((row) => row.actionable).length;
  const waiting = rows.some((row) => row.card?.state === "waiting");
  const matches = rows.filter((row) => (!attentionOnly || row.actionable)
    && `${row.name} ${row.symbol}`.toLowerCase().includes(query.trim().toLowerCase()));
  const discipline = board.discipline;
  const tradeCount = discipline.inside_count + discipline.outside_count
    + discipline.undecidable_count + discipline.sell_count;

  return <div className="dl-tracking">
    <header className="dl-tracking-header">
      <div>
        <h1>我的跟踪</h1>
        <p>{attention > 0 ? `${attention} 家有待关注的变化，已排在前面。`
          : board.total > 0 ? "当前没有待处理记录，接着看你的研究。"
          : rows.length > 0 ? "已有资料都在这里，挑一家接着看。" : "从一家你关心的公司开始。"}</p>
      </div>
      <div className="dl-tracking-tools">
        {waiting && <button type="button" className="text-button" disabled={busy}
          onClick={() => void refresh(true)}>检查价格条件</button>}
        <button type="button" className="page-action page-action--row page-action--small" disabled={busy}
          onClick={() => void refresh()}>{busy ? "正在更新…" : "刷新"}</button>
      </div>
    </header>
    {error && <p className="form-error" role="alert">刷新失败，以下保留上次读取的资料。{error}</p>}
    {scanNote && <p className="dl-tracking-notice" role="status">{scanNote}</p>}

    <section className="dl-tracking-sheet" aria-label="公司跟踪清单">
      <div className="dl-tracking-bar">
        <div className="dl-tracking-filter">
          <button type="button" aria-pressed={!attentionOnly}
            onClick={() => { setAttentionOnly(false); setLimit(12); }}>全部公司 <span>{rows.length}</span></button>
          {(attention > 0 || attentionOnly) && <button type="button" aria-pressed={attentionOnly}
            onClick={() => { setAttentionOnly(true); setLimit(12); }}>需要关注 <span>{attention}</span></button>}
        </div>
        {rows.length > 8 && <input type="search" aria-label="筛选跟踪公司" placeholder="搜索这份清单"
          value={query} onChange={(event) => { setQuery(event.target.value); setLimit(12); }} />}
      </div>
      {rows.length > 0 && <div className="dl-tracking-columns" aria-hidden="true">
        <span>公司</span><span>当前情况与已有研究</span><span>参考价 / 日期</span><span>接着看</span>
      </div>}
      <ul className="dl-tracking-list">
        {matches.slice(0, limit).map((row) => {
          const card = row.card;
          const note = row.actionable && card ? card.entered_reason || card.watch_reason
            : row.latest_claim || row.report_title || card?.watch_reason;
          const stateLabel = card?.state === "triggered" ? "价格进入设定区间"
            : card?.state === "discovered" && (row.thesis_count + row.valuation_count + row.report_count > 0)
              ? "已有研究" : card?.state_label;
          return <li key={row.company_id} className={row.actionable ? "dl-tracking-row is-attention" : "dl-tracking-row"}>
            <div className="dl-tracking-company">
              <button type="button" onClick={() => onOpenCompany(row.company_id)}>{row.name}</button>
              <span>{row.symbol}{row.is_sample ? " · 示例" : row.industry ? ` · ${row.industry}` : ""}</span>
            </div>
            <div className="dl-tracking-context">
              <div className="dl-tracking-state">
                {card && <strong>{stateLabel}</strong>}
                {card?.ideal_low != null && card?.ideal_high != null && <span>
                  理想区 {MONEY(card.ideal_low)}–{MONEY(card.ideal_high)}</span>}
                <span>{researchSummary(row)}</span>
              </div>
              {note ? <p title={note}>{note === row.latest_claim && row.thesis_status ? `${THESIS_LABELS[row.thesis_status] || "判断"}：` : ""}{note.replace(/\*\*/g, "")}</p>
                : <p>{card ? "可打开计划查看价格条件和下一步。" : "尚未写下判断，可先查看公司资料。"}</p>}
            </div>
            <div className="dl-tracking-price">
              <span>{MONEY(row.price)}</span>
              <small>{row.price_date?.slice(0, 10) || "暂无行情记录"}</small>
            </div>
            <div className="dl-tracking-actions">
              <button type="button" className="text-button" onClick={() => onOpenCompany(row.company_id,
                row.latest_claim ? "research" : row.report_count > 0 ? "chain" : row.valuation_count > 0 ? "market" : undefined)}>查看研究</button>
              {card ? <button type="button" className="text-button" onClick={() => setOpen(row.company_id)}>
                {row.actionable ? "查看变化" : "查看计划"}</button>
                : <button type="button" className="text-button" disabled={busy}
                    onClick={() => void startTracking(row.company_id)}>设置计划</button>}
            </div>
          </li>;
        })}
      </ul>
      {matches.length === 0 && <p className="dl-tracking-empty">
        {rows.length === 0 ? "还没有公司档案。用上方搜索找到公司，即可开始研究。"
          : query ? "没有匹配的公司，换个名称或代码试试。" : "当前没有待关注的记录。"}
      </p>}
      {matches.length > limit && <button type="button" className="text-button dl-tracking-more"
        onClick={() => setLimit((value) => value + 20)}>再显示 20 家（还有 {matches.length - limit} 家）</button>}
      <footer className="dl-tracking-foot">
        <span>{board.total > 0 ? `${board.total} 家已进入跟踪` : "尚未设置跟踪计划"} · 已有资料无需重新录入</span>
        <span>资料读取于 {readAt}，行情日期见各行</span>
      </footer>
    </section>

    {tradeCount > 0 && <details className="dl-tracking-discipline">
      <summary>交易纪律 <span>{tradeCount} 笔记录{discipline.outside_count > 0
        ? `，${discipline.outside_count} 笔计划外买入` : ""}</span></summary>
      <div className="dl-discipline">
      <dl className="dl-counts">
        <div><dt>计划内买入</dt><dd>{discipline.inside_count}</dd></div>
        <div><dt>计划外买入</dt><dd>{discipline.outside_count}</dd></div>
        <div><dt>无法判定</dt><dd>{discipline.undecidable_count}</dd></div>
        <div><dt>卖出（未判定）</dt><dd>{discipline.sell_count}</dd></div>
      </dl>
      {discipline.outside.length > 0 && <>
        <h4>这几笔在计划外</h4>
        <ul className="dl-trades">
          {discipline.outside.map((trade) => <li key={trade.id}>
            <span>{trade.trade_date} · {trade.company_name} · {MONEY(trade.price)}</span>
            <em>{rich(trade.why ?? "")}</em>
          </li>)}
        </ul>
      </>}
      {discipline.undecidable.length > 0 && <details className="dl-undecidable">
        <summary>{discipline.undecidable_count} 笔缺少判断依据</summary>
        <ul className="dl-trades">
          {discipline.undecidable.map((trade) => <li key={trade.id}>
            <span>{trade.trade_date} · {trade.company_name} · {MONEY(trade.price)}</span>
            <em>{trade.why}</em>
          </li>)}
        </ul>
      </details>}
      <p className="dl-sell-note">按成交时保存的计划核对买入记录。</p>
      </div>
    </details>}
  </div>;
}
