/**
 * 三情景估值。
 *
 * ## 排版顺序 = 这一页的立场
 *
 * 反推 → 价值区间 → 三情景输入 → 敏感度。
 *
 * **反推排第一，因为它是唯一不含预测成分的那个数**：「现在的价格要求这家公司
 * 未来五年收入年增多少」是关于当前价格的一个事实。三个情景是"你怎么看"，
 * 反推是"市场怎么看"。把它排在前面，问题就从"贵不贵"变成一个具体的问题——
 * 这个增速，它过去五年做到过吗？
 *
 * ## 为什么画成一条数轴，不画成三根柱子
 *
 * 三根柱子会让人去比较柱子的高矮，而这里真正的问题是**现价落在这个区间的哪儿**。
 * 数轴把"悲观 / 基准 / 乐观 / 现价"放在同一条尺上，那个位置本身就是答案。
 *
 * 现价的记号跟三个情景刻意长得不一样：**它是事实，那三个是条件推论**。
 * 长得一样会让人以为四个数是同一类东西。
 *
 * ## 假设旁边必须摆历史实际值
 *
 * 一个人填 25% 增速时，往往不知道这家公司过去五年只做到 11.9%。
 * 把实际值摆在输入框旁边，是这套东西唯一能防住自欺的地方——
 * 比任何"温馨提示"都有用。
 *
 * ## 退出 PE 单独做敏感度
 *
 * 它是整套里最主观的一个数，而五年后的价值直接乘它。不单列的话，
 * 人会盯着增速反复调，却对那个一锤定音的数毫无感觉。
 */

import { useEffect, useMemo, useState } from "react";

import { valueOf, impliedGrowth, inYi } from "../lib/valuation";
import { Boundary } from "./Boundary";

import {
  getValuation, getValuationDrift, saveValuation,
  type ValuationView, type ValuationDrift,
} from "../api";
import { chartInk, chartPalette } from "./chartTokens";

type Draft = { key: string; revenue_growth: number; net_margin: number; exit_pe: number };

const BAND = chartPalette.blue;

function errorText(caught: unknown): string {
  return caught instanceof Error ? caught.message : String(caught);
}

function rich(text: string) {
  return text.split(/\*\*/).map((part, index) =>
    index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>);
}

function yi(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value / 1e8).toFixed(0)} 亿`;
}

/** 价值区间数轴：三个情景 + 现价放在同一条尺上。位置本身就是答案。 */
/** 尺子只需要「叫什么、值多少」。**不要求整个 ValuationScenarioRow** ——
 *  实时算出来的行只有这三样，而尺子本来也只用这三样。 */
type RulerRow = { key: string; label: string; per_share: number | null };

function Ruler({ rows, price }: { rows: RulerRow[]; price: number | null | undefined }) {
  const values = rows.map((r) => r.per_share).filter((v): v is number => v !== null);
  if (values.length === 0 || !price) return null;

  // **对数刻度。** 三个情景常常差一两个数量级（宁德实测 68 / 255 / 3508），
  // 线性尺下最大的那个把另外三个全挤到最左边一团 —— 尺子于是什么都没说。
  // 取对数之后 68 和 255 才分得开，而"差几倍"这件事本来就该用等距表示。
  const lo = Math.min(...values, price);
  const hi = Math.max(...values, price);
  const log = (v: number) => Math.log10(Math.max(v, 0.01));
  const from = log(lo);
  const span = log(hi) - from || 1;
  // 两端各留 6%，否则最左和最右那个标签有一半在框外
  const at = (v: number) => 6 + ((log(v) - from) / span) * 88;

  // **标签会撞在一起。** 基准 255 和现价 305 只差 16%，在尺子上几乎同一个点。
  // 按位置排序后交替上下错行，撞的那两个就分得开了。
  const marks = [
    ...rows.filter((r) => r.per_share !== null)
           .map((r) => ({ key: r.key, label: r.label, value: r.per_share as number, now: false })),
    { key: "__now__", label: "现价", value: price, now: true },
  ].sort((a, b) => a.value - b.value);
  const placed = marks.map((mark, index) => {
    const previous = index > 0 ? marks[index - 1] : null;
    const tight = previous !== null && Math.abs(at(mark.value) - at(previous.value)) < 11;
    return { ...mark, low: tight && index % 2 === 1 };
  });

  return (
    <figure className="vs-fig">
      <figcaption>现价落在你的假设区间哪儿<span>横轴 = 每股价值（元，对数刻度）</span></figcaption>
      <div className="vs-ruler" role="img"
           aria-label={rows.map((r) => `${r.label} ${r.per_share ?? "算不出"}`).join("，") + `，现价 ${price}`}>
        <i className="vs-axis" />
        {placed.map((mark) => (
          // 现价的记号刻意跟三个情景不同：**它是事实，那三个是条件推论**
          <span key={mark.key}
                className={`vs-mark${mark.now ? " vs-mark--now" : ""}${mark.low ? " vs-mark--low" : ""}`}
                style={{ left: `${at(mark.value)}%` }}>
            <b style={{ background: mark.now ? chartInk.strong : BAND }} />
            <em>{mark.label}<br />{mark.value.toFixed(0)}</em>
          </span>
        ))}
      </div>
      <p className="chart-note">
        三个刻度是<strong>条件推论</strong>——假设成立才成立；现价是<strong>事实</strong>。
        两者不是同一类东西，所以记号长得不一样。
      </p>
    </figure>
  );
}

/** 你说过的话。
 *
 * **这是这套系统唯一不可替代的能力的第一个具体形态。** 数据不稀缺、分析也不稀缺了，
 * 这台机器真正做得比人好的只有一件：它不会心软。你的朋友不会当面问
 * 「股价涨了 23% 之后你把假设调高了，这中间什么都没发生，你是在给它找理由吗」，
 * 你自己更不会问。
 *
 * 排在页面**底部**是刻意的：它不是每次来都要看的东西，但一旦有话要问，
 * 那句话必须够重。所以有 ask 级的问题时整块会亮起来。
 */
function Drift({ data }: { data: ValuationDrift }) {
  if (data.changes.length === 0) {
    return (
      <div className="vs-drift vs-drift--quiet">
        <h4>你说过的话</h4>
        <p>{data.saves <= 1
          ? "只存过一次假设，还没有可比的。改过之后这里会告诉你改了什么、当时发生了什么。"
          : "假设改动都在噪音范围内，没什么可问的。"}</p>
      </div>
    );
  }
  return (
    <div className={`vs-drift${data.open_questions > 0 ? " vs-drift--ask" : ""}`}>
      <h4>你说过的话{data.open_questions > 0 && <em>{data.open_questions} 个待回答</em>}</h4>
      <p className="vs-drift-summary">{rich(data.summary)}</p>
      {data.changes.map((item) => (
        <article className={`vs-drift-item vs-drift-item--${item.reading.level}`}
                 key={item.change.to_at}>
          <div className="vs-drift-head">
            <strong>{item.reading.headline}</strong>
            <span>{item.change.from_at?.slice(0, 10)} → {item.change.to_at?.slice(0, 10)}</span>
          </div>
          <p className="vs-drift-fields">
            {item.change.fields.map((f) => (
              <span key={f.key}>{f.label} {f.before}{f.unit} → <b>{f.after}{f.unit}</b></span>
            ))}
          </p>
          {item.reading.question.split("\n\n").map((para, index) => (
            <p className="vs-drift-q" key={index}>{rich(para)}</p>
          ))}
        </article>
      ))}
      <p className="chart-note">{rich(data.boundary)}</p>
    </div>
  );
}

export function ValuationScenarios({ companyId }: { companyId: number }) {
  const [view, setView] = useState<ValuationView | null>(null);
  const [drift, setDrift] = useState<ValuationDrift | null>(null);
  const [draft, setDraft] = useState<Draft[]>([]);
  const [years, setYears] = useState(5);
  const [discount, setDiscount] = useState(10);
  const [busy, setBusy] = useState(false);
  const [said, setSaid] = useState("");
  const [error, setError] = useState("");

  function adopt(next: ValuationView) {
    setView(next);
    setDraft((next.scenarios ?? []).map((row) => ({
      key: row.key, revenue_growth: row.revenue_growth,
      net_margin: row.net_margin, exit_pe: row.exit_pe,
    })));
    setYears(next.years ?? 5);
    setDiscount(next.discount_rate ?? 10);
  }

  async function reloadDrift() {
    try { setDrift(await getValuationDrift(companyId)); } catch { /* 漂移读不到不该挡住估值本身 */ }
  }

  useEffect(() => {
    let live = true;
    getValuation(companyId).then((next) => { if (live) { adopt(next); setError(""); } })
      .catch((caught) => { if (live) setError(errorText(caught)); });
    void reloadDrift();
    return () => { live = false; };
  }, [companyId]);

  // ── 边改边算 ──────────────────────────────────────────────────────────
  //
  // 这里原来读的是服务端上次算好的 `view.scenarios`，于是输入框改了、右边那一列
  // 纹丝不动，要按「存下这组假设」才会变。使用者的原话是
  // 「那几个每股价值都不会变化的，是我看不懂、还是 bug」。是 bug。
  //
  // **这个 useMemo 必须待在所有提前 return 的上面。**
  // 第一版放在 `if (!view) return …` 后面 —— 首屏走不到它、拿到数据后走到了，
  // 于是 hook 数量在两次渲染之间变了，整页当场白屏
  // （Rendered more hooks than during the previous render）。
  //
  // 公式跟后端逐行对应，两侧一致性由 lib/valuation.test.ts 钉着。
  const facts = {
    baseRevenue: view?.base_revenue ?? 0,
    shares: view?.shares ?? 0,
    years,
    discountRate: discount,
  };
  const live = useMemo(() => new Map(draft.map((row) => [row.key, valueOf({
    revenueGrowth: row.revenue_growth, netMargin: row.net_margin, exitPe: row.exit_pe,
  }, facts)])), [draft, years, discount, view?.base_revenue, view?.shares]);

  async function save() {
    setBusy(true); setSaid(""); setError("");
    try {
      adopt(await saveValuation(companyId, { years, discount_rate: discount, scenarios: draft }));
      await reloadDrift();     // 存完立刻回看：这次改动会不会被问一句
      setSaid("已存下这组假设。旧的那份留着——那是你判断变迁的记录。");
    } catch (caught) { setError(errorText(caught)); } finally { setBusy(false); }
  }

  function edit(key: string, field: keyof Draft, value: number) {
    setDraft((rows) => rows.map((row) => row.key === key ? { ...row, [field]: value } : row));
  }

  if (error) return <p className="form-error">{error}</p>;
  if (!view) return <div className="empty-state">正在读取估值…</div>;

  if (!view.ready) {
    return (
      <div className="empty-state vs-empty">
        <p>{view.note}</p>
        {view.missing.length > 0 && <ul>{view.missing.map((m) => <li key={m}>缺：{m}</li>)}</ul>}
      </div>
    );
  }

  const history = view.history;

  const liveRows = draft.map((row) => ({
    key: row.key,
    label: (view.scenarios ?? []).find((s) => s.key === row.key)?.label ?? row.key,
    per_share: live.get(row.key)?.perShare ?? null,
  }));
  // 反推也跟着现在填的净利率与退出 PE 走（拿基准那一行的）
  const baseRow = draft.find((row) => row.key === "base") ?? draft[1] ?? draft[0];
  const liveImplied = baseRow && view.price
    ? impliedGrowth(view.price, { revenueGrowth: baseRow.revenue_growth,
        netMargin: baseRow.net_margin, exitPe: baseRow.exit_pe }, facts)
    : null;

  const dirty = JSON.stringify(draft) !== JSON.stringify((view.scenarios ?? []).map((r) => ({
    key: r.key, revenue_growth: r.revenue_growth, net_margin: r.net_margin, exit_pe: r.exit_pe })))
    || years !== view.years || discount !== view.discount_rate;

  return <>
    {/* 反推排第一：它是唯一不含预测成分的那个数 */}
    {view.implied_verdict && (
      <div className="vs-implied">
        <span className="eyebrow">当前价格隐含的要求</span>
        <p>{rich(view.implied_verdict)}</p>
        {/* 反推跟着基准那一行的净利率与退出 PE 走 —— 你改了它们，这句也要跟着变，
            否则页面上会同时摆着两套互不相干的假设。 */}
        {liveImplied !== null && view.implied_growth !== null
          && Math.abs(liveImplied - (view.implied_growth ?? 0)) > 0.01 && (
          <p className="vs-implied-live">
            按你现在填的基准（净利率 {baseRow?.net_margin}%、退出 PE {baseRow?.exit_pe}、
            {years} 年）重算：<strong>{liveImplied.toFixed(2)}%</strong>
          </p>
        )}
      </div>
    )}

    <Ruler rows={liveRows} price={view.price} />

    <div className="vs-controls">
      <label>看几年
        <input type="number" min={1} max={10} value={years}
               onChange={(e) => setYears(Number(e.target.value))} />
      </label>
      <label>折现率（你要求的年化回报）
        <input type="number" min={0} max={40} step={0.5} value={discount}
               onChange={(e) => setDiscount(Number(e.target.value))} />%
      </label>
      <span className="vs-basis">
        起点：{view.base_report_date ?? "—"} 年报，营收 {yi(view.base_revenue)}
      </span>
    </div>

    {/* 初值的出处。**放在表外一行，不塞进单元格** ——
        塞进去之后三行说明把输入框挤得东倒西歪，反而更难读。 */}
    {!view.saved && view.seed_sources?.note && (
      <div className="vs-seed-note">
        <p>{rich(view.seed_sources.note)}</p>
        <ul>
          {(["bear", "base", "bull"] as const).map((key) => {
            const text = view.seed_sources?.[key];
            const label = (view.scenarios ?? []).find((s) => s.key === key)?.label ?? key;
            return text ? <li key={key}><b>{label}</b>{text}</li> : null;
          })}
        </ul>
      </div>
    )}

    <div className="vs-table-wrap">
      <table className="vs-table">
        <thead>
          <tr>
            <th>情景</th>
            <th>收入年增 %</th>
            <th>净利率 %</th>
            <th>退出 PE</th>
            {/* **把 N 年后的营收摆出来，假设才能被证伪。**
                乐观情景算出每股三千多的时候，这一列会写着「3.57 万亿」——
                比中国石化还大。那个数字自己会说话，比任何提示都管用。 */}
            <th>{years} 年后营收</th>
            <th>每股价值</th>
            <th>相对现价</th>
          </tr>
        </thead>
        <tbody>
          {draft.map((row) => {
            const computed = live.get(row.key);
            const label = (view.scenarios ?? []).find((s) => s.key === row.key)?.label;
            const gap = computed?.perShare && view.price
              ? (computed.perShare / view.price - 1) * 100 : null;
            return (
              <tr key={row.key}>
                <th scope="row">{label ?? row.key}</th>
                <td><input type="number" step={0.1} value={row.revenue_growth}
                           onChange={(e) => edit(row.key, "revenue_growth", Number(e.target.value))} /></td>
                <td><input type="number" step={0.1} value={row.net_margin}
                           onChange={(e) => edit(row.key, "net_margin", Number(e.target.value))} /></td>
                <td><input type="number" step={0.1} value={row.exit_pe}
                           onChange={(e) => edit(row.key, "exit_pe", Number(e.target.value))} /></td>
                <td className="vs-future">{inYi(computed?.futureRevenue)}</td>
                <td className="vs-value">{computed?.perShare?.toFixed(0) ?? "—"}</td>
                <td className="vs-gap">{gap === null ? "—" : `${gap > 0 ? "+" : ""}${gap.toFixed(0)}%`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>

    {/* **历史实际值必须挨着输入框。** 填 25% 的人往往不知道它过去只做到 11.9%，
        而这是整页唯一能防住自欺的地方。 */}
    {history && (
      <div className="vs-actual">
        <h4>它实际做到过什么</h4>
        <dl>
          <div><dt>收入复合增速</dt><dd>
            五年 {history.cagr_5y ?? "—"}% · 三年 {history.cagr_3y ?? "—"}%
          </dd></div>
          <div><dt>单年增速区间</dt><dd>
            最差 {history.growth_worst ?? "—"}% · 最好 {history.growth_best ?? "—"}%
          </dd></div>
          <div><dt>净利率</dt><dd>
            {history.margin_low ?? "—"}% ~ {history.margin_high ?? "—"}%（中位 {history.margin_median ?? "—"}%）
          </dd></div>
          {view.pe_band && view.pe_band.covered > 0 && <div><dt>它自己的 PE 分位</dt><dd>
            P25 {view.pe_band.p25?.toFixed(1)} · 中位 {view.pe_band.p50?.toFixed(1)} · P75 {view.pe_band.p75?.toFixed(1)}
            {view.current_pe ? `（当前 ${view.current_pe.toFixed(1)}）` : ""}
          </dd></div>}
        </dl>
        <p className="chart-note">{history.stat_note}</p>
      </div>
    )}

    {/* 退出 PE 最主观，而五年后的价值直接乘它——不单列的话，人会盯着增速反复调，
        却对那个一锤定音的数毫无感觉。 */}
    {view.sensitivity && view.sensitivity.length > 0 && (
      <div className="vs-sens">
        <h4>换个退出 PE 会怎样</h4>
        <div className="vs-sens-row">
          {view.sensitivity.map((item) => (
            <div key={item.label}>
              <span>{item.label}</span>
              <em>PE {item.exit_pe}</em>
              <strong>{item.per_share?.toFixed(0) ?? "—"}</strong>
            </div>
          ))}
        </div>
        <p className="chart-note">
          增速和净利率都没动，只动退出 PE。<strong>它是整套里最主观的一个数</strong>，
          而五年后的价值直接乘它。
        </p>
      </div>
    )}

    <div className="vs-actions">
      {/* **没存过的时候不许说「已是保存的状态」。**
          初值跟草稿一样时 dirty=false，于是按钮写着"已保存"、
          旁边同一行却写着"还没填过" —— 页面自己跟自己打架，
          而这一步恰恰是闭环里卡着的那一格（决策卡要求「做过一次估值」）。 */}
      <button className="page-action" disabled={busy || (!dirty && view.saved)}
              onClick={() => void save()}>
        {busy ? "正在保存…"
          : !view.saved ? "就用这组初值，存下来"
          : dirty ? "存下这组假设" : "已是保存的状态"}
      </button>
      <span className="vs-said">
        {said || (view.saved
          ? `上次保存于 ${view.saved_at?.slice(0, 16).replace("T", " ")}${view.price_at_write ? `，当时股价 ${view.price_at_write.toFixed(2)}` : ""}`
          : view.seeded_from)}
      </span>
    </div>

    {drift && <Drift data={drift} />}

    <Boundary text={view.boundary ?? ""} />
  </>;
}
