/**
 * 做 T 回测：「我没做 T，是不是少赚了」这一问的机器回答。
 *
 * ## 这一页的顺序是论证的顺序，不是数据的顺序
 *
 * 1. **规律到底有没有** —— 没有规律的话，后面的收益数字全是噪声，不用看。
 * 2. **天花板有多高** —— 每天神操作能赚多少。连它都不够看就到此为止。
 * 3. **成本是不是瓶颈** —— 把"亏在手续费"和"亏在猜方向"分开。
 * 4. **四条策略各自的结果** —— 到这里才谈具体做法。
 *
 * 反过来排（先给收益表、再解释）的话，人会先看到一个收益数字，
 * 然后用后面的文字去给它找理由。**先给结论再给数据，等于先射箭后画靶。**
 *
 * ## 亏损不涂红
 *
 * 这一页上负数很多，而它们不是错误——「做 T 会亏钱」正是要传达的结论。
 * 涂红会让它读起来像报警，而报警是会被关掉的。
 */

import { useCallback, useEffect, useState } from "react";

import { getCompanies, getSwingStudy, type SwingRun, type SwingView } from "../api";
import type { CompanyRecord } from "../types";
import { PanelTitle } from "./PanelTitle";

function rich(text: string) {
  return text.split(/\*\*/).map((part, index) =>
    index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>);
}

function pct(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;
}
function signed(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

/** p 值怎么读。**只给一句话，不给星号** —— 星号会被当成"越多越好"。 */
function readP(p: number | null | undefined, alpha: number): string {
  if (p === null || p === undefined) return "样本不足，不做检验";
  if (p < alpha) return `p=${p.toFixed(3)}，低于 ${alpha} 的门槛：这个偏差不像是碰巧`;
  return `p=${p.toFixed(3)}，没有低过 ${alpha} 的门槛：这个偏差可能只是碰巧`;
}

function Conditional({ row, alpha }: { row: NonNullable<SwingView["rhythm"]["reversal"]>; alpha: number }) {
  return <div className="sw-cond">
    <h4>{row.label}</h4>
    <p className="sw-cond-big">{row.rate === null ? "—" : `${(row.rate * 100).toFixed(1)}%`}</p>
    <dl>
      <div><dt>样本</dt><dd>{row.hits} / {row.total} 天</dd></div>
      {/* **基准是这里最要紧的一行。** 「涨完之后 52% 会跌」听起来像规律，
          跟 51% 的基准比就什么都不是。 */}
      <div><dt>基准（什么都不看）</dt><dd>{(row.base * 100).toFixed(1)}%</dd></div>
      <div><dt>比基准高</dt><dd>{row.lift === null ? "—" : `${(row.lift * 100).toFixed(1)} 个百分点`}</dd></div>
    </dl>
    <p className="sw-p">{readP(row.p_value, alpha)}</p>
  </div>;
}

function Curve({ run }: { run: SwingRun }) {
  const points = run.curve ?? [];
  if (points.length < 2) return null;
  const values = points.map((p) => p.cumulative);
  const high = Math.max(...values, 0);
  const low = Math.min(...values, 0);
  const span = high - low || 1;
  const path = points.map((point, index) => {
    const x = (index / (points.length - 1)) * 100;
    const y = 30 - ((point.cumulative - low) / span) * 30;
    return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const zero = 30 - ((0 - low) / span) * 30;
  return <svg className="sw-curve" viewBox="0 0 100 30" preserveAspectRatio="none"
              role="img" aria-label={`${run.label}的累计净收益曲线`}>
    <line x1="0" y1={zero} x2="100" y2={zero} className="sw-curve-zero" />
    <path d={path} className="sw-curve-line" />
  </svg>;
}

function RunCard({ run, ceiling }: { run: SwingRun; ceiling: boolean }) {
  if (!run.trades) {
    return <article className={`sw-run${ceiling ? " sw-run--ceiling" : ""}`}>
      <header><h4>{run.label}</h4></header>
      <p className="sw-run-empty">{run.note}</p>
    </article>;
  }
  return <article className={`sw-run${ceiling ? " sw-run--ceiling" : ""}`}>
    <header>
      <h4>{run.label}</h4>
      <span className="sw-run-net">
        {run.net === undefined ? "—" : `${run.net > 0 ? "+" : ""}${Math.round(run.net).toLocaleString("zh-CN")} 元`}
        <em>{run.net_percent === null || run.net_percent === undefined
          ? "" : `底仓的 ${signed(run.net_percent, 2)}%`}</em>
      </span>
    </header>
    {run.blurb && <p className="sw-run-blurb">{rich(run.blurb)}</p>}
    <Curve run={run} />
    <dl className="sw-run-stats">
      <div><dt>成交</dt><dd>{run.trades} 次</dd></div>
      <div><dt>胜率</dt><dd>{pct(run.win_rate, 0)}</dd></div>
      <div><dt>毛价差</dt><dd>{Math.round(run.gross ?? 0).toLocaleString("zh-CN")} 元</dd></div>
      <div><dt>费用</dt><dd>{Math.round(run.fees ?? 0).toLocaleString("zh-CN")} 元</dd></div>
      <div><dt>单笔均值</dt><dd>{Math.round(run.net_per_trade ?? 0).toLocaleString("zh-CN")} 元</dd></div>
      <div><dt>打平所需价差</dt><dd>{pct(run.breakeven_spread, 2)}</dd></div>
    </dl>
    {/* **正收益必须当场配上「它可能只是运气」那个数。**
        不配的话，这一页上唯一留在脑子里的就是那个收益率——
        而一个好看的回测最容易让人下重注。

        天花板那张卡除外：**完美预知当然显著**（实测 p=0.000、t=27.42），
        把这行挂上去只会让"谁也做不到的那条线"看起来像被统计验证过。 */}
    {!ceiling && (run.net ?? 0) > 0 && <p className="sw-run-luck">
      {(() => {
        const p = run.win_rate_p_value;
        const t = run.t_stat;
        const winOk = p !== null && p !== undefined ? p < 0.05 : null;
        const tOk = t !== null && t !== undefined ? Math.abs(t) > 2 : null;
        const parts: string[] = [];
        // **两个口径对不上的时候要明说。** 一个说"赢的次数比抛硬币多"、
        // 一个说"单笔收益跟 0 分不开"，多半是几笔大的把总收益抬起来了——
        // 只报其中一个，读起来就是一个被验证过的策略。
        if (winOk !== null && tOk !== null && winOk !== tOk) parts.push("**两个口径对不上**");
        if (p !== null && p !== undefined) {
          parts.push(`胜率跟抛硬币${winOk ? "分得开" : "分不开"}（p=${p.toFixed(3)}）`);
        }
        if (t !== null && t !== undefined) {
          parts.push(`单笔收益 t=${t.toFixed(2)}${tOk ? "（不像纯运气）" : "（跟 0 分不开）"}`);
        }
        if (run.small_sample) parts.push(`样本只有 ${run.trades} 笔，统计上算少`);
        return rich(parts.join("；"));
      })()}
    </p>}
    {/* **被跳过的天数必须露出来。** 不露的话，"规则没触发"和"触发了但没数据"
        在页面上长得一模一样，而后者是回测虚高最常见的来源。 */}
    {(run.skipped_locked > 0 || run.skipped_no_open > 0) && <p className="sw-run-skip">
      跳过：一字板 {run.skipped_locked} 天{run.skipped_no_open > 0 ? ` · 缺开盘价 ${run.skipped_no_open} 天` : ""}
    </p>}
  </article>;
}

export function SwingLab({ onOpenCompany, initialCompanyId }: { onOpenCompany: (id: number) => void; initialCompanyId?: number }) {
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [companyId, setCompanyId] = useState<number | null>(initialCompanyId ?? null);
  const [window_, setWindow] = useState(250);
  const [trigger, setTrigger] = useState(1);
  const [baseShares, setBaseShares] = useState(10000);
  const [tactical, setTactical] = useState(20);
  const [view, setView] = useState<SwingView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    getCompanies().then((rows) => {
      if (!live) return;
      setCompanies(rows);
      setCompanyId((current) => current ?? rows[0]?.id ?? null);
    }).catch((caught) => live && setError(String(caught instanceof Error ? caught.message : caught)));
    return () => { live = false; };
  }, []);

  const load = useCallback(async () => {
    if (companyId === null) return;
    setBusy(true); setError("");
    try {
      setView(await getSwingStudy(companyId, {
        window: window_, trigger_percent: trigger,
        base_shares: baseShares, tactical_percent: tactical,
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      setView(null);
    } finally { setBusy(false); }
  }, [companyId, window_, trigger, baseShares, tactical]);

  useEffect(() => { void load(); }, [load]);

  const rhythm = view?.rhythm;
  const ceilingRun = view?.runs.find((run) => run.strategy === "oracle");
  const realRuns = view?.runs.filter((run) => run.strategy !== "oracle") ?? [];

  return <>
    {initialCompanyId === undefined && <section className="page-intro archive-intro">
      <div>
        <span className="section-kicker">SWING</span>
        <h1>做 T，值不值</h1>
        <p><strong>「没做 T」不等于「少赚」</strong>，它可能只是少交易了。
           这一页只做算术：那条"一天涨一天跌"的规律存不存在，
           存在的话扣完手续费和印花税还剩多少。<strong>不调模型，不花积分。</strong></p>
      </div>
      {view && <div className="local-stamp"><span>BARS</span>
        <strong>{view.bars_available.toLocaleString("zh-CN")} 根日线</strong></div>}
    </section>}

    <section className="panel jd-panel">
      <div className="sw-controls">
        {initialCompanyId === undefined && <>        <label>
          <span>股票</span>
          <select disabled={initialCompanyId !== undefined} value={companyId ?? ""} onChange={(event) => setCompanyId(Number(event.target.value))}>
            {companies.map((company) =>
              <option key={company.id} value={company.id}>{company.name}（{company.symbol}）</option>)}
          </select>
        </label></>}
        <label>
          <span>回看窗口</span>
          <select value={window_} onChange={(event) => setWindow(Number(event.target.value))}>
            <option value={120}>近 120 个交易日</option>
            <option value={250}>近 250 个交易日（约一年）</option>
            <option value={500}>近 500 个交易日</option>
            <option value={0}>有多少用多少</option>
          </select>
        </label>
        <label>
          <span>触发门槛（昨日涨/跌超过）</span>
          <input type="number" min={0} max={20} step={0.5} value={trigger}
                 onChange={(event) => setTrigger(Number(event.target.value))} />
        </label>
        <label>
          <span>底仓股数</span>
          <input type="number" min={100} step={100} value={baseShares}
                 onChange={(event) => setBaseShares(Number(event.target.value))} />
        </label>
        <label>
          <span>战术仓占底仓</span>
          <input type="number" min={1} max={100} step={5} value={tactical}
                 onChange={(event) => setTactical(Number(event.target.value))} />
        </label>
        {companyId !== null && <button type="button" className="text-button"
                onClick={() => onOpenCompany(companyId)}>打开公司档案 →</button>}
      </div>
      {view?.shares_held ? <p className="sw-held">
        账本里这只票实际持有 {view.shares_held.toLocaleString("zh-CN")} 股。
        <button type="button" className="text-button"
                onClick={() => setBaseShares(Math.round(view.shares_held as number))}>
          按这个数重算
        </button>
        <em>结论里最要紧的几个（有没有规律、天花板多高、打平要多少价差）跟股数无关。</em>
      </p> : null}
      {error && <p className="form-error">{error}</p>}
      {busy && !view && <div className="empty-state">正在算…</div>}
    </section>

    {view && rhythm && <>
      {/* ① 规律到底有没有 */}
      <section className="panel jd-panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">第一问</span>
          <PanelTitle hint="没有规律的话，后面的收益数字全是噪声。">
            那条「一天涨一天跌」，存不存在
          </PanelTitle>
        </div>
        {rhythm.verdict && <span className={`sw-verdict sw-verdict--${
          rhythm.verdict === "有反转倾向" ? "yes" : rhythm.verdict === "证据不一致" ? "mixed" : "no"}`}>
          {rhythm.verdict}</span>}
        </div>
        {!rhythm.enough ? <p className="empty-state">{rhythm.note}</p> : <>
          <p className="sw-headline">{rich(rhythm.headline ?? "")}</p>
          <div className="sw-conds">
            {rhythm.reversal && <Conditional row={rhythm.reversal} alpha={rhythm.alpha ?? 0.025} />}
            {rhythm.rebound && <Conditional row={rhythm.rebound} alpha={rhythm.alpha ?? 0.025} />}
            <div className="sw-cond sw-cond--rho">
              <h4>一阶自相关</h4>
              <p className="sw-cond-big">{rhythm.autocorrelation_1?.toFixed(3) ?? "—"}</p>
              <p className="sw-rho-note">{rich(
                "「今天的涨跌跟昨天反着来」翻成数字就是这一项为负。"
                + "**贴着 0 的话，你看到的是随机序列长出来的花纹**——随机序列一定会长出花纹。")}</p>
              <dl><div><dt>滞后两天</dt><dd>{rhythm.autocorrelation_2?.toFixed(3) ?? "—"}</dd></div></dl>
            </div>
          </div>
          <dl className="sw-facts">
            <div><dt>窗口</dt><dd>{rhythm.start} → {rhythm.end}（{rhythm.days} 天）</dd></div>
            <div><dt>涨 / 跌 / 平</dt><dd>{rhythm.up_days} / {rhythm.down_days} / {rhythm.flat_days}</dd></div>
            <div><dt>平均日振幅</dt><dd>{pct(rhythm.mean_amplitude, 2)}</dd></div>
            <div><dt>平均日涨跌绝对值</dt><dd>{pct(rhythm.mean_abs_return, 2)}</dd></div>
            <div><dt>年化波动（窗口）</dt><dd>{pct(rhythm.volatility_window, 1)}</dd></div>
            <div><dt>年化波动（近 20 日）</dt><dd>{pct(rhythm.volatility_20d, 1)}</dd></div>
            <div><dt>最长连涨</dt><dd>{rhythm.runs?.max_up ?? "—"} 天</dd></div>
            <div><dt>最长连跌</dt><dd>{rhythm.runs?.max_down ?? "—"} 天</dd></div>
          </dl>
        </>}
      </section>

      {/* ② 天花板 + ③ 成本是不是瓶颈 */}
      <section className="panel jd-panel sw-ceiling">
        <div className="panel-heading"><div>
          <span className="eyebrow">第二问</span>
          <PanelTitle hint="连天花板都不够看的话，后面的调参不必开始。">
            做 T 这件事，最多值多少
          </PanelTitle>
        </div></div>
        <p className="sw-headline">{rich(view.ceiling_line)}</p>
        {view.cost_line && <p className="sw-headline sw-headline--second">{rich(view.cost_line)}</p>}
        {ceilingRun && <RunCard run={ceilingRun} ceiling />}
      </section>

      {/* ④ 四条策略 */}
      <section className="panel jd-panel">
        <div className="panel-heading"><div>
          <span className="eyebrow">第三问</span>
          <PanelTitle hint="日终仓位都还原，所以这里的净收益本身就是超额——不用再跟买入持有相减。">
            照着规则做，结果是什么
          </PanelTitle>
        </div></div>
        <p className="sw-headline">{rich(view.best_line)}</p>
        {view.missing_open_days > 0 && <p className="sw-warn">
          这个窗口里有 <strong>{view.missing_open_days} 天缺开盘价</strong>，三条真实策略在那些天
          成交不了。去公司档案点一次「同步行情历史」可以把它补齐。
        </p>}
        <div className="sw-runs">
          {realRuns.map((run) => <RunCard key={run.strategy} run={run} ceiling={false} />)}
        </div>
        <details className="sw-strategies">
          <summary>这四条规则各自是什么，为什么只有这几条</summary>
          <dl>
            {Object.entries(view.strategies).map(([key, spec]) => <div key={key}>
              <dt>{spec.label}</dt>
              <dd>{rich(spec.blurb)}<em>{spec.why}</em></dd>
            </div>)}
          </dl>
        </details>
      </section>

      <section className="panel jd-panel sw-caveats">
        <div className="panel-heading"><div>
          <PanelTitle hint="回测最容易骗人的几处，写在这里而不是脚注里。">这份模拟做不到什么</PanelTitle>
        </div></div>
        <ul>{view.caveats.map((line, index) => <li key={index}>{rich(line)}</li>)}</ul>
      </section>
    </>}
  </>;
}
